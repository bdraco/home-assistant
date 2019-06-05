"""Support for Nexia / Trane XL Thermostats."""
import logging

from requests.exceptions import ConnectTimeout, HTTPError
import voluptuous as vol

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, CONF_ID, CONF_SCAN_INTERVAL
import homeassistant.helpers.config_validation as cv

REQUIREMENTS = [
    "beautifulsoup4==4.6.3",
    "certifi==2018.8.24",
    "chardet==3.0.4",
    "html5lib==1.0.1",
    "idna==2.7",
    "requests==2.19.1",
    "six==1.11.0",
    "urllib3==1.23",
    "webencodings==0.5.1"
]

_LOGGER = logging.getLogger(__name__)

ATTRIBUTION = "Data provided by nexiahome.com"

NOTIFICATION_ID = 'nexia_notification'
NOTIFICATION_TITLE = 'Nexia Setup'

DATA_NEXIA = 'nexia'
DOMAIN = 'nexia'
DEFAULT_ENTITY_NAMESPACE = 'nexia'

ATTR_FAN = 'fan'
ATTR_SYSTEM_MODE = 'system_mode'
ATTR_CURRENT_OPERATION = 'system_status'
ATTR_MODEL = "model"
ATTR_FIRMWARE = 'firmware'
ATTR_THERMOSTAT_NAME = 'thermostat_name'
ATTR_HOLD_MODES = 'hold_modes'
ATTR_SETPOINT_STATUS = 'setpoint_status'
ATTR_ZONE_STATUS = 'zone_status'
ATTR_FAN_SPEED = 'fan_speed'
ATTR_COMPRESSOR_SPEED = 'compressor_speed'
ATTR_OUTDOOR_TEMPERATURE = 'outdoor_temperature'


CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_ID): cv.positive_int,
        vol.Optional(CONF_SCAN_INTERVAL): cv.positive_int
    }),
}, extra=vol.ALLOW_EXTRA)


def setup(hass, config):
    from .nexia_thermostat import NexiaThermostat

    conf = config[DOMAIN]

    username = conf[CONF_USERNAME]
    password = conf[CONF_PASSWORD]
    house_id = conf[CONF_ID]

    scan_interval = conf.get(CONF_SCAN_INTERVAL, NexiaThermostat.UPDATE_RATE)

    try:
        thermostat = NexiaThermostat(username=username, password=password, house_id=house_id, update_rate=scan_interval)
        hass.data[DATA_NEXIA] = thermostat
    except (ConnectTimeout, HTTPError) as ex:
        _LOGGER.error("Unable to connect to Nexia service: %s", str(ex))
        hass.components.persistent_notification.create(
            'Error: {}<br />'
            'You will need to restart hass after fixing.'
            ''.format(ex),
            title=NOTIFICATION_TITLE,
            notification_id=NOTIFICATION_ID)
        return False
    return True
