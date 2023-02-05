"""Constants for the ScreenLogic integration."""
from screenlogicpy.const import CIRCUIT_FUNCTION, COLOR_MODE

from homeassistant.util import slugify

DOMAIN = "screenlogic"
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10

SERVICE_SET_COLOR_MODE = "set_color_mode"
ATTR_COLOR_MODE = "color_mode"
SUPPORTED_COLOR_MODES = {
    slugify(name): num for num, name in COLOR_MODE.NAME_FOR_NUM.items()
}

LIGHT_CIRCUIT_FUNCTIONS = {
    CIRCUIT_FUNCTION.COLOR_WHEEL,
    CIRCUIT_FUNCTION.DIMMER,
    CIRCUIT_FUNCTION.INTELLIBRITE,
    CIRCUIT_FUNCTION.LIGHT,
    CIRCUIT_FUNCTION.MAGICSTREAM,
    CIRCUIT_FUNCTION.PHOTONGEN,
    CIRCUIT_FUNCTION.SAL_LIGHT,
    CIRCUIT_FUNCTION.SAM_LIGHT,
}
