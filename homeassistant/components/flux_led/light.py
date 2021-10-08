"""Support for FluxLED/MagicHome lights."""
from __future__ import annotations

import ast
import logging
import random
from typing import Any, Final, cast

from flux_led.aiodevice import AIOWifiLedBulb
from flux_led.const import (
    COLOR_MODE_CCT as FLUX_COLOR_MODE_CCT,
    COLOR_MODE_DIM as FLUX_COLOR_MODE_DIM,
    COLOR_MODE_RGB as FLUX_COLOR_MODE_RGB,
    COLOR_MODE_RGBW as FLUX_COLOR_MODE_RGBW,
    COLOR_MODE_RGBWW as FLUX_COLOR_MODE_RGBWW,
)
from flux_led.device import MAX_TEMP, MIN_TEMP
from flux_led.utils import rgbw_brightness, rgbww_brightness
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_WHITE,
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_HS,
    COLOR_MODE_ONOFF,
    COLOR_MODE_RGBW,
    COLOR_MODE_RGBWW,
    COLOR_MODE_WHITE,
    EFFECT_COLORLOOP,
    EFFECT_RANDOM,
    PLATFORM_SCHEMA,
    SUPPORT_EFFECT,
    SUPPORT_TRANSITION,
    LightEntity,
)
from homeassistant.const import (
    ATTR_MANUFACTURER,
    ATTR_MODE,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_SW_VERSION,
    CONF_DEVICES,
    CONF_HOST,
    CONF_MAC,
    CONF_MODE,
    CONF_NAME,
    CONF_PROTOCOL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_platform
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.color import (
    color_hs_to_RGB,
    color_RGB_to_hs,
    color_temperature_kelvin_to_mired,
    color_temperature_mired_to_kelvin,
)

from . import FluxLedUpdateCoordinator
from .const import (
    CONF_AUTOMATIC_ADD,
    CONF_COLORS,
    CONF_CUSTOM_EFFECT,
    CONF_CUSTOM_EFFECT_COLORS,
    CONF_CUSTOM_EFFECT_SPEED_PCT,
    CONF_CUSTOM_EFFECT_TRANSITION,
    CONF_SPEED_PCT,
    CONF_TRANSITION,
    DEFAULT_EFFECT_SPEED,
    DOMAIN,
    FLUX_HOST,
    FLUX_LED_DISCOVERY,
    FLUX_MAC,
    MODE_AUTO,
    MODE_RGB,
    MODE_RGBW,
    MODE_WHITE,
    SIGNAL_STATE_UPDATED,
    TRANSITION_GRADUAL,
    TRANSITION_JUMP,
    TRANSITION_STROBE,
)

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLUX_LED: Final = SUPPORT_EFFECT | SUPPORT_TRANSITION


FLUX_COLOR_MODE_TO_HASS: Final = {
    # hs color used to avoid dealing with brightness conversions
    FLUX_COLOR_MODE_RGB: COLOR_MODE_HS,
    FLUX_COLOR_MODE_RGBW: COLOR_MODE_RGBW,
    FLUX_COLOR_MODE_RGBWW: COLOR_MODE_RGBWW,
    FLUX_COLOR_MODE_CCT: COLOR_MODE_COLOR_TEMP,
    FLUX_COLOR_MODE_DIM: COLOR_MODE_WHITE,
}


# Constant color temp values for 2 flux_led special modes
# Warm-white and Cool-white modes
COLOR_TEMP_WARM_VS_COLD_WHITE_CUT_OFF: Final = 285

# List of supported effects which aren't already declared in LIGHT
EFFECT_RED_FADE: Final = "red_fade"
EFFECT_GREEN_FADE: Final = "green_fade"
EFFECT_BLUE_FADE: Final = "blue_fade"
EFFECT_YELLOW_FADE: Final = "yellow_fade"
EFFECT_CYAN_FADE: Final = "cyan_fade"
EFFECT_PURPLE_FADE: Final = "purple_fade"
EFFECT_WHITE_FADE: Final = "white_fade"
EFFECT_RED_GREEN_CROSS_FADE: Final = "rg_cross_fade"
EFFECT_RED_BLUE_CROSS_FADE: Final = "rb_cross_fade"
EFFECT_GREEN_BLUE_CROSS_FADE: Final = "gb_cross_fade"
EFFECT_COLORSTROBE: Final = "colorstrobe"
EFFECT_RED_STROBE: Final = "red_strobe"
EFFECT_GREEN_STROBE: Final = "green_strobe"
EFFECT_BLUE_STROBE: Final = "blue_strobe"
EFFECT_YELLOW_STROBE: Final = "yellow_strobe"
EFFECT_CYAN_STROBE: Final = "cyan_strobe"
EFFECT_PURPLE_STROBE: Final = "purple_strobe"
EFFECT_WHITE_STROBE: Final = "white_strobe"
EFFECT_COLORJUMP: Final = "colorjump"
EFFECT_CUSTOM: Final = "custom"

EFFECT_MAP: Final = {
    EFFECT_COLORLOOP: 0x25,
    EFFECT_RED_FADE: 0x26,
    EFFECT_GREEN_FADE: 0x27,
    EFFECT_BLUE_FADE: 0x28,
    EFFECT_YELLOW_FADE: 0x29,
    EFFECT_CYAN_FADE: 0x2A,
    EFFECT_PURPLE_FADE: 0x2B,
    EFFECT_WHITE_FADE: 0x2C,
    EFFECT_RED_GREEN_CROSS_FADE: 0x2D,
    EFFECT_RED_BLUE_CROSS_FADE: 0x2E,
    EFFECT_GREEN_BLUE_CROSS_FADE: 0x2F,
    EFFECT_COLORSTROBE: 0x30,
    EFFECT_RED_STROBE: 0x31,
    EFFECT_GREEN_STROBE: 0x32,
    EFFECT_BLUE_STROBE: 0x33,
    EFFECT_YELLOW_STROBE: 0x34,
    EFFECT_CYAN_STROBE: 0x35,
    EFFECT_PURPLE_STROBE: 0x36,
    EFFECT_WHITE_STROBE: 0x37,
    EFFECT_COLORJUMP: 0x38,
}
EFFECT_ID_NAME: Final = {v: k for k, v in EFFECT_MAP.items()}
EFFECT_CUSTOM_CODE: Final = 0x60

FLUX_EFFECT_LIST: Final = sorted(EFFECT_MAP) + [EFFECT_RANDOM]

SERVICE_CUSTOM_EFFECT: Final = "set_custom_effect"

CUSTOM_EFFECT_DICT: Final = {
    vol.Required(CONF_COLORS): vol.All(
        cv.ensure_list,
        vol.Length(min=1, max=16),
        [vol.All(vol.ExactSequence((cv.byte, cv.byte, cv.byte)), vol.Coerce(tuple))],
    ),
    vol.Optional(CONF_SPEED_PCT, default=50): vol.All(
        vol.Range(min=0, max=100), vol.Coerce(int)
    ),
    vol.Optional(CONF_TRANSITION, default=TRANSITION_GRADUAL): vol.All(
        cv.string, vol.In([TRANSITION_GRADUAL, TRANSITION_JUMP, TRANSITION_STROBE])
    ),
}

CUSTOM_EFFECT_SCHEMA: Final = vol.Schema(CUSTOM_EFFECT_DICT)

DEVICE_SCHEMA: Final = vol.Schema(
    {
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(ATTR_MODE, default=MODE_AUTO): vol.All(
            cv.string, vol.In([MODE_AUTO, MODE_RGBW, MODE_RGB, MODE_WHITE])
        ),
        vol.Optional(CONF_PROTOCOL): vol.All(cv.string, vol.In(["ledenet"])),
        vol.Optional(CONF_CUSTOM_EFFECT): CUSTOM_EFFECT_SCHEMA,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_DEVICES, default={}): {cv.string: DEVICE_SCHEMA},
        vol.Optional(CONF_AUTOMATIC_ADD, default=False): cv.boolean,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> bool:
    """Set up the flux led platform."""
    domain_data = hass.data[DOMAIN]
    discovered_mac_by_host = {
        device[FLUX_HOST]: device[FLUX_MAC]
        for device in domain_data[FLUX_LED_DISCOVERY]
    }
    for host, device_config in config.get(CONF_DEVICES, {}).items():
        _LOGGER.warning(
            "Configuring flux_led via yaml is deprecated; the configuration for"
            " %s has been migrated to a config entry and can be safely removed",
            host,
        )
        custom_effects = device_config.get(CONF_CUSTOM_EFFECT, {})
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data={
                    CONF_HOST: host,
                    CONF_MAC: discovered_mac_by_host.get(host),
                    CONF_NAME: device_config[CONF_NAME],
                    CONF_PROTOCOL: device_config.get(CONF_PROTOCOL),
                    CONF_MODE: device_config.get(ATTR_MODE, MODE_AUTO),
                    CONF_CUSTOM_EFFECT_COLORS: str(custom_effects.get(CONF_COLORS)),
                    CONF_CUSTOM_EFFECT_SPEED_PCT: custom_effects.get(
                        CONF_SPEED_PCT, DEFAULT_EFFECT_SPEED
                    ),
                    CONF_CUSTOM_EFFECT_TRANSITION: custom_effects.get(
                        CONF_TRANSITION, TRANSITION_GRADUAL
                    ),
                },
            )
        )
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Flux lights."""
    coordinator: FluxLedUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_CUSTOM_EFFECT,
        CUSTOM_EFFECT_DICT,
        "async_set_custom_effect",
    )
    options = entry.options

    try:
        custom_effect_colors = ast.literal_eval(
            options.get(CONF_CUSTOM_EFFECT_COLORS) or "[]"
        )
    except (ValueError, TypeError, SyntaxError, MemoryError) as ex:
        _LOGGER.warning(
            "Could not parse custom effect colors for %s: %s", entry.unique_id, ex
        )
        custom_effect_colors = []

    async_add_entities(
        [
            FluxLight(
                coordinator,
                entry.unique_id,
                entry.data[CONF_NAME],
                list(custom_effect_colors),
                options.get(CONF_CUSTOM_EFFECT_SPEED_PCT, DEFAULT_EFFECT_SPEED),
                options.get(CONF_CUSTOM_EFFECT_TRANSITION, TRANSITION_GRADUAL),
            )
        ]
    )


class FluxLight(CoordinatorEntity, LightEntity):
    """Representation of a Flux light."""

    coordinator: FluxLedUpdateCoordinator

    def __init__(
        self,
        coordinator: FluxLedUpdateCoordinator,
        unique_id: str | None,
        name: str,
        custom_effect_colors: list[tuple[int, int, int]],
        custom_effect_speed_pct: int,
        custom_effect_transition: str,
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator)
        self._bulb: AIOWifiLedBulb = coordinator.device
        self._responding = True
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._attr_supported_features = SUPPORT_FLUX_LED
        self._attr_min_mireds = (
            color_temperature_kelvin_to_mired(MAX_TEMP) + 1
        )  # for rounding
        self._attr_max_mireds = color_temperature_kelvin_to_mired(MIN_TEMP)
        color_modes = {
            FLUX_COLOR_MODE_TO_HASS.get(mode, COLOR_MODE_ONOFF)
            for mode in self._bulb.color_modes
        }
        if COLOR_MODE_RGBW in color_modes or COLOR_MODE_RGBWW in color_modes:
            # Backwards compat
            color_modes.update({COLOR_MODE_HS, COLOR_MODE_COLOR_TEMP})
        self._attr_supported_color_modes = color_modes
        self._attr_effect_list = FLUX_EFFECT_LIST
        if custom_effect_colors:
            self._attr_effect_list = [*FLUX_EFFECT_LIST, EFFECT_CUSTOM]
        self._custom_effect_colors = custom_effect_colors
        self._custom_effect_speed_pct = custom_effect_speed_pct
        self._custom_effect_transition = custom_effect_transition
        if self.unique_id:
            old_protocol = self._bulb.protocol == "LEDENET_ORIGINAL"
            raw_state = self._bulb.raw_state
            self._attr_device_info = {
                "connections": {(dr.CONNECTION_NETWORK_MAC, self.unique_id)},
                ATTR_MODEL: f"0x{self._bulb.model_num:02X}",
                ATTR_NAME: self.name,
                ATTR_SW_VERSION: "1" if old_protocol else str(raw_state.version_number),
                ATTR_MANUFACTURER: "FluxLED/Magic Home",
            }

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        return cast(bool, self._bulb.is_on)

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        return cast(int, self._bulb.brightness)

    @property
    def color_temp(self) -> int:
        """Return the kelvin value of this light in mired."""
        return color_temperature_kelvin_to_mired(self._bulb.getWhiteTemperature()[0])

    @property
    def hs_color(self) -> tuple[float, float]:
        """Return the hs color value."""
        raw = self._bulb.raw_state
        return color_RGB_to_hs(raw.red, raw.green, raw.blue)

    @property
    def rgbw_color(self) -> tuple[int, int, int, int]:
        """Return the rgbw color value."""
        raw = self._bulb.raw_state
        return (raw.red, raw.green, raw.blue, raw.warm_white)

    @property
    def rgbww_color(self) -> tuple[int, int, int, int, int]:
        """Return the rgbww color value."""
        raw = self._bulb.raw_state
        return (raw.red, raw.green, raw.blue, raw.warm_white, raw.cool_white)

    @property
    def color_mode(self) -> str:
        """Return the color mode of the light."""
        return FLUX_COLOR_MODE_TO_HASS.get(self._bulb.color_mode, COLOR_MODE_ONOFF)

    @property
    def effect(self) -> str | None:
        """Return the current effect."""
        if (current_mode := self._bulb.raw_state.preset_pattern) == EFFECT_CUSTOM_CODE:
            return EFFECT_CUSTOM
        return EFFECT_ID_NAME.get(current_mode)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Return the attributes."""
        return {"ip_address": self._bulb.ipaddr}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the specified or all lights on."""
        await self._async_turn_on(**kwargs)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def _async_turn_on(self, **kwargs: Any) -> None:
        """Turn the specified or all lights on."""
        if not self.is_on:
            await self._bulb.async_turn_on()
            if not kwargs:
                return

        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is None:
            brightness = self.brightness

        # Handle switch to CCT Color Mode
        if ATTR_COLOR_TEMP in kwargs:
            color_temp_mired = kwargs[ATTR_COLOR_TEMP]
            color_temp_kelvin = color_temperature_mired_to_kelvin(color_temp_mired)
            await self._bulb.async_set_white_temp(color_temp_kelvin, brightness)
            return
        # Handle switch to HS Color Mode
        if ATTR_HS_COLOR in kwargs:
            await self._bulb.async_set_levels(
                *color_hs_to_RGB(*kwargs[ATTR_HS_COLOR]), brightness=brightness
            )
            return
        # Handle switch to RGBW Color Mode
        if ATTR_RGBW_COLOR in kwargs:
            if ATTR_BRIGHTNESS in kwargs:
                rgbw = rgbw_brightness(kwargs[ATTR_RGBW_COLOR], brightness)
            else:
                rgbw = kwargs[ATTR_RGBW_COLOR]
            await self._bulb.async_set_levels(*rgbw)
            return
        # Handle switch to RGBWW Color Mode
        if ATTR_RGBWW_COLOR in kwargs:
            if ATTR_BRIGHTNESS in kwargs:
                rgbww = rgbww_brightness(kwargs[ATTR_RGBWW_COLOR], brightness)
            else:
                rgbww = kwargs[ATTR_RGBWW_COLOR]
            await self._bulb.async_set_levels(*rgbww)
            return
        # Handle switch to White Color Mode
        if ATTR_WHITE in kwargs:
            await self._bulb.async_set_levels(w=kwargs[ATTR_WHITE])
            return
        if ATTR_EFFECT in kwargs:
            effect = kwargs[ATTR_EFFECT]
            # Random color effect
            if effect == EFFECT_RANDOM:
                await self._bulb.async_set_levels(
                    random.randint(0, 255),
                    random.randint(0, 255),
                    random.randint(0, 255),
                )
                return
            # Custom effect
            if effect == EFFECT_CUSTOM:
                if self._custom_effect_colors:
                    await self._bulb.async_set_custom_pattern(
                        self._custom_effect_colors,
                        self._custom_effect_speed_pct,
                        self._custom_effect_transition,
                    )
                return
            # Effect selection
            if effect in EFFECT_MAP:
                await self._bulb.async_set_preset_pattern(
                    EFFECT_MAP[effect], DEFAULT_EFFECT_SPEED
                )
                return
            raise ValueError(f"Unknown effect {effect}")
        # Handle brightness adjustment in CCT Color Mode
        if self.color_mode == COLOR_MODE_COLOR_TEMP:
            await self._bulb.async_set_white_temp(
                self._bulb.getWhiteTemperature()[0], brightness
            )
            return
        # Handle brightness adjustment in RGB Color Mode
        if self.color_mode == COLOR_MODE_HS:
            rgb = color_hs_to_RGB(*self.hs_color)
            await self._bulb.async_set_levels(*rgb, brightness=brightness)
            return
        # Handle brightness adjustment in RGBW Color Mode
        if self.color_mode == COLOR_MODE_RGBW:
            await self._bulb.async_set_levels(
                *rgbw_brightness(self.rgbw_color, brightness)
            )
            return
        # Handle brightness adjustment in RGBWW Color Mode
        if self.color_mode == COLOR_MODE_RGBWW:
            rgbww = rgbww_brightness(self.rgbww_color, brightness)
            await self._bulb.async_set_levels(*rgbww)
            return
        # Handle White Color Mode and Brightness Only Color Mode
        if self.color_mode in (COLOR_MODE_WHITE, COLOR_MODE_BRIGHTNESS):
            await self._bulb.async_set_levels(w=brightness)
            return
        raise ValueError(f"Unsupported color mode {self.color_mode}")

    async def async_set_custom_effect(
        self, colors: list[tuple[int, int, int]], speed_pct: int, transition: str
    ) -> None:
        """Set a custom effect on the bulb."""
        await self._bulb.async_set_custom_pattern(
            colors,
            speed_pct,
            transition,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the specified or all lights off."""
        await self._bulb.async_turn_off()
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.last_update_success != self._responding:
            self.async_write_ha_state()
        self._responding = self.coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_STATE_UPDATED.format(self._bulb.ipaddr),
                self.async_write_ha_state,
            )
        )
        await super().async_added_to_hass()
