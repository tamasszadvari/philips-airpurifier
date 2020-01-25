from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import urllib.request
import base64
import binascii
import json
import random
import asyncio

import voluptuous as vol

from homeassistant.const import CONF_NAME, CONF_HOST, CONF_TOKEN, ATTR_ENTITY_ID
import homeassistant.helpers.config_validation as cv

from homeassistant.components.fan import (
    ATTR_SPEED,
    DOMAIN,
    PLATFORM_SCHEMA,
    SPEED_OFF,
    SUPPORT_SET_SPEED,
    FanEntity
)

__version__ = '0.4.0'

G = int('A4D1CBD5C3FD34126765A442EFB99905F8104DD258AC507FD6406CFF14266D31266FEA1E5C41564B777E690F5504F213160217B4B01B886A5E91547F9E2749F4D7FBD7D3B9A92EE1909D0D2263F80A76A6A24C087A091F531DBF0A0169B6A28AD662A4D18E73AFA32D779D5918D08BC8858F4DCEF97C2A24855E6EEB22B3B2E5', 16)
P = int('B10B8F96A080E01DDE92DE5EAE5D54EC52C99FBCFB06A3C69A6A9DCA52D23B616073E28675A23D189838EF1E2EE652C013ECB4AEA906112324975C3CD49B83BFACCBDD7D90C4BD7098488E9C219A73724EFFD6FAE5644738FAA31A4FF55BCCC0A151AF5F0DC8B4BD45BF37DF365C1A65E68CFDA76D4DA708DF1FB2BC2E4A4371', 16)

DATA_KEY = "fan.philips_airpurifier"

CONF_HOST = 'host'
CONF_NAME = 'name'

FEATURE_SET_CHILD_LOCK = 4
FEATURE_SET_LED_BRIGHTNESS = 8

FEATURE_FLAGS_FAN = (
    FEATURE_SET_CHILD_LOCK
    | FEATURE_SET_LED_BRIGHTNESS
)

ATTR_BRIGHTNESS = "brightness"
ATTR_BUTTON_LIGHT = "button_light"

SERVICE_SET_LED_BRIGHTNESS = "philips_airpurifier_set_led_brightness"
SERVICE_SET_BUTTON_LIGHT = "philips_airpurifier_set_button_light"

DEFAULT_NAME = 'Philips AirPurifier'
ICON = 'mdi:air-purifier'

SPEED_LIST = ['Auto Mode', 'Allergen Mode', 'Bacteria Mode', 'Sleep Mode', 'Speed 1', 'Speed 2', 'Speed 3', 'Turbo']

AIRPURIFIER_SERVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_ids})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
})

SERVICE_SCHEMA_LED_BRIGHTNESS = AIRPURIFIER_SERVICE_SCHEMA.extend(
    {vol.Required(ATTR_BRIGHTNESS): vol.All(vol.Coerce(int), vol.Clamp(min=0, max=100))}
)
SERVICE_SCHEMA_BUTTON_LIGHT = AIRPURIFIER_SERVICE_SCHEMA.extend(
    {vol.Required(ATTR_BUTTON_LIGHT): cv.string,}
)

### Encrypting and Decrypting for Philips ###

def aes_decrypt(data, key):
    iv = bytes(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.decrypt(data)

def encrypt(values, key):
    data = 'AA' + json.dumps(values)
    data = pad(bytearray(data, 'ascii'), 16, style='pkcs7')
    iv = bytes(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    data_enc = cipher.encrypt(data)
    return base64.b64encode(data_enc)

def decrypt(data, key):
    payload = base64.b64decode(data)
    data = aes_decrypt(payload, key)
    response = unpad(data, 16, style='pkcs7')[2:]
    return response.decode('ascii')

### Setup Platform ###

async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    device = PhilipsAirPurifierFan(hass, config)
    
    async_add_devices([device])
    
    async def async_led_brightness_handler(service):
        brightness = service.data.get(ATTR_BRIGHTNESS, 100)
        await device.async_set_led_brightness(brightness)
        device.async_schedule_update_ha_state(True)

    async def async_button_light_handler(service):
        button_light = service.data.get(ATTR_BUTTON_LIGHT, '1')
        await device.async_set_button_light(button_light)
        device.async_schedule_update_ha_state(True)

    hass.services.async_register(
        DOMAIN, SERVICE_SET_LED_BRIGHTNESS, async_led_brightness_handler, schema=SERVICE_SCHEMA_LED_BRIGHTNESS
    )
    
    hass.services.async_register(
        DOMAIN, SERVICE_SET_BUTTON_LIGHT, async_button_light_handler, schema=SERVICE_SCHEMA_BUTTON_LIGHT
    )

class PhilipsAirPurifierFan(FanEntity):
    def __init__(self, hass, config):
        self.hass = hass
        self._host = config[CONF_HOST]
        self._name = config[CONF_NAME]
        self._state = None
        self._session_key = None
        
        self._device_features = FEATURE_FLAGS_FAN
        
        self._mode = None
        self._fan_speed = None
        
        self._pre_filter = None
        self._wick_filter = None
        self._carbon_filter = None
        self._hepa_filter = None
        
        self._pm25 = None
        self._humidity = None
        self._target_humidity = None
        self._allergen_index = None
        self._temperature = None
        self._function = None
        self._light_brightness = None
        self._used_index = None
        self._water_level = None
        self._child_lock = None
        self._button_light = None
        
        self.update()
    
    ### Update Fan attributes ###
    
    def update(self):
        url = 'http://{}/di/v1/products/1/fltsts'.format(self._host)
        filters = self._get(url)
        self._pre_filter = filters['fltsts0']
        if 'wicksts' in filters:
            self._wick_filter = filters['wicksts']
        self._carbon_filter = filters['fltsts2']
        self._hepa_filter = filters['fltsts1']
        
        url = 'http://{}/di/v1/products/1/air'.format(self._host)
        status = self._get(url)
        if 'pwr' in status:
            if status['pwr'] == '1':
                self._state = 'on'
            else:
                self._state = 'off'
        if 'pm25' in status:
            self._pm25 = status['pm25']
        if 'rh' in status:
            self._humidity = status['rh']
        if 'rhset' in status:
            self._target_humidity = status['rhset']
        if 'iaql' in status:
            self._allergen_index = status['iaql']
        if 'temp' in status:
            self._temperature = status['temp']
        if 'func' in status:
            func = status['func']
            func_str = {'P': 'Purification', 'PH': 'Purification & Humidification'}
            self._function = func_str.get(func, func)
        if 'mode' in status:
            mode = status['mode']
            mode_str = {'P': 'Auto Mode', 'A': 'Allergen Mode', 'S': 'Sleep Mode', 'M': 'Manual', 'B': 'Bacteria', 'N': 'Night'}
            self._mode = mode_str.get(mode, mode)
            self._fan_speed = mode_str.get(mode, mode)
        if 'om' in status:
            om = status['om']
            om_str = {'s': 'Silent', 't': 'Turbo', '1': 'Speed 1', '2': 'Speed 2', '3': 'Speed 3'}
            om = om_str.get(om, om)
            if self._fan_speed == 'Manual':
                self._fan_speed = om
        if 'aqil' in status:
            self._light_brightness = status['aqil']
        if 'ddp' in status:
            ddp = status['ddp']
            ddp_str = {'1': 'PM2.5', '0': 'IAI'}
            self._used_index = ddp_str.get(ddp, ddp)
        if 'wl' in status:
            self._water_level = status['wl']
        if 'cl' in status:
            self._child_lock = status['cl']
        if 'uil' in status:
            uil = status['uil']
            uil_str = {'1': 'On', '0': 'Off'}
            self._button_light = uil_str.get(uil, uil)
    
    ### Properties ###
    
    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORT_SET_SPEED
    
    @property
    def state(self):
        return self._state
    
    @property
    def name(self):
        return self._name
    
    @property
    def icon(self):
        return ICON
    
    @property
    def speed_list(self) -> list:
        return SPEED_LIST
    
    @property
    def speed(self) -> str:
        return self._fan_speed

    @property
    def mode(self) -> str:
        return self._mode
        
    @property
    def light_brightness(self) -> int:
        return self._light_brightness
    
    def turn_on(self, speed: str = None, **kwargs) -> None:
        if speed is None:
            values = {}
            values['pwr'] = '1'
            self.set_values(values)
        else:
            self.set_speed(speed)

    def turn_off(self, **kwargs) -> None:
        values = {}
        values['pwr'] = '0'
        self.set_values(values)
    
    def set_speed(self, speed: str) -> None:
        values = {}
        if speed == 'Turbo':
            values['mode'] = 'M'
            values['om'] = 't'
        elif speed == 'Speed 1':
            values['mode'] = 'M'
            values['om'] = '1'
        elif speed == 'Speed 2':
            values['mode'] = 'M'
            values['om'] = '2'
        elif speed == 'Speed 3':
            values['mode'] = 'M'
            values['om'] = '3'
        elif speed == 'P':
            values['mode'] = 'P'
        elif speed == 'Auto Mode':
            values['mode'] = 'P'
        elif speed == 'Allergen Mode':
            values['mode'] = 'A'
        elif speed == 'Bacteria Mode':
            values['mode'] = 'B'
        elif speed == 'Sleep Mode':
            values['mode'] = 'M'
            values['om'] = 's'
        self.set_values(values)
        
    async def async_set_speed(self, speed: str):
        self.set_speed(self, speed)

    async def async_set_led_brightness(self, brightness: int = 100):
        values = {}
        values['aqil'] = brightness
        self.set_values(values)

    async def async_set_button_light(self, button_light):
        values = {}
        values['uil'] = button_light
        self.set_values(values)
    
    @property
    def device_state_attributes(self):
        attr = {}
        if self._function != None:
          attr['function'] = self._function
        if self._used_index != None:
          attr['used_index'] = self._used_index
        if self._pm25 != None:
          attr['pm25'] = self._pm25
        if self._allergen_index != None:
          attr['allergen_index'] = self._allergen_index
        if self._temperature != None:
          attr['temperature'] = self._temperature
        if self._humidity != None:
          attr['humidity'] = self._humidity
        if self._target_humidity != None:
          attr['target_humidity'] = self._target_humidity
        if self._water_level != None:
          attr['water_level'] = self._water_level
        if self._light_brightness != None:
          attr['light_brightness'] = self._light_brightness
        if self._child_lock != None:
          attr['child_lock'] = self._child_lock
        if self._pre_filter != None:
          attr['pre_filter'] = self._pre_filter
        if self._wick_filter != None:
          attr['wick_filter'] = self._wick_filter
        if self._carbon_filter != None:
          attr['carbon_filter'] = self._carbon_filter
        if self._hepa_filter != None:
          attr['hepa_filter'] = self._hepa_filter
        if self._mode != None:
          attr['mode'] = self._mode
        if self._button_light != None:
          attr['button_light'] = self._button_light
        return attr
    
    ### Other methods ###
    
    def set_values(self, values):
        body = encrypt(values, self._session_key)
        url = 'http://{}/di/v1/products/1/air'.format(self._host)
        req = urllib.request.Request(url=url, data=body, method='PUT')
        with urllib.request.urlopen(req) as response:
            resp = response.read()
    
    def _get_key(self):
        url = 'http://{}/di/v1/products/0/security'.format(self._host)
        a = random.getrandbits(256)
        A = pow(G, a, P)
        data = json.dumps({'diffie': format(A, 'x')})
        data_enc = data.encode('ascii')
        req = urllib.request.Request(url=url, data=data_enc, method='PUT')
        with urllib.request.urlopen(req) as response:
            resp = response.read().decode('ascii')
            dh = json.loads(resp)
        key = dh['key']
        B = int(dh['hellman'], 16)
        s = pow(B, a, P)
        s_bytes = s.to_bytes(128, byteorder='big')[:16]
        session_key = aes_decrypt(bytes.fromhex(key), s_bytes)
        self._session_key = session_key[:16]
    
    def _get_once(self, url):
        with urllib.request.urlopen(url) as response:
            resp = response.read()
            resp = decrypt(resp.decode('ascii'), self._session_key)
            return json.loads(resp)

    def _get(self, url):
        try:
            return self._get_once(url)
        except Exception as e:
            self._get_key()
            return self._get_once(url)
