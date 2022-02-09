"""WiZ integration light platform."""
from __future__ import annotations

import logging
from typing import Any

from pywizlight import PilotBuilder
from pywizlight.bulblibrary import BulbClass, BulbType, Features
from pywizlight.scenes import get_id_from_scene_name

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_RGBW,
    COLOR_MODE_RGBWW,
    COLOR_MODES_COLOR,
    SUPPORT_EFFECT,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import (
    color_temperature_kelvin_to_mired,
    color_temperature_mired_to_kelvin,
)

from .const import DOMAIN
from .entity import WizToggleEntity
from .models import WizData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the WiZ Platform from config_flow."""
    wiz_data: WizData = hass.data[DOMAIN][entry.entry_id]
    if wiz_data.bulb.bulbtype.bulb_type != BulbClass.SOCKET:
        async_add_entities([WizBulbEntity(wiz_data, entry.title)])


class WizBulbEntity(WizToggleEntity, LightEntity):
    """Representation of WiZ Light bulb."""

    def __init__(self, wiz_data: WizData, name: str) -> None:
        """Initialize an WiZLight."""
        super().__init__(wiz_data, name)
        bulb_type: BulbType = self._device.bulbtype
        features: Features = bulb_type.features
        color_modes = set()
        if features.color:
            if bulb_type.white_channels == 2:
                color_modes.add(COLOR_MODE_RGBWW)
            color_modes.add(COLOR_MODE_RGBW)
        if features.color_tmp:
            color_modes.add(COLOR_MODE_COLOR_TEMP)
        if not color_modes and features.brightness:
            color_modes.add(COLOR_MODE_BRIGHTNESS)
        self._attr_supported_color_modes = color_modes
        self._attr_effect_list = wiz_data.scenes
        if bulb_type.bulb_type != BulbClass.DW:
            self._attr_min_mireds = color_temperature_kelvin_to_mired(
                bulb_type.kelvin_range.max
            )
            self._attr_max_mireds = color_temperature_kelvin_to_mired(
                bulb_type.kelvin_range.min
            )
        if bulb_type.features.effect:
            self._attr_supported_features = SUPPORT_EFFECT
        self._async_update_attrs()

    @callback
    def _async_update_attrs(self) -> None:
        """Handle updating _attr values."""
        state = self._device.state
        color_modes = self.supported_color_modes
        assert color_modes is not None
        if (brightness := state.get_brightness()) is not None:
            self._attr_brightness = max(0, min(255, brightness))
        if COLOR_MODE_COLOR_TEMP in color_modes and state.get_colortemp() is not None:
            self._attr_color_mode = COLOR_MODE_COLOR_TEMP
            if color_temp := state.get_colortemp():
                self._attr_color_temp = color_temperature_kelvin_to_mired(color_temp)
        elif (
            COLOR_MODES_COLOR.intersection(color_modes)
            and (rgb := state.get_rgb()) is not None
            and rgb[0] is not None
        ):
            warm = state.get_warm_white() or 0
            if COLOR_MODE_RGBWW in color_modes:
                cold = state.get_cold_white() or 0
                self._attr_rgbww_color = (rgb[0], rgb[1], rgb[2], cold, warm)
                self._attr_color_mode = COLOR_MODE_RGBW
            else:
                self._attr_rgbw_color = (rgb[0], rgb[1], rgb[2], warm)
                self._attr_color_mode = COLOR_MODE_RGBWW
        else:
            self._attr_color_mode = COLOR_MODE_BRIGHTNESS
        self._attr_effect = state.get_scene()
        super()._async_update_attrs()

    @callback
    def _async_pilot_builder(self, **kwargs: Any) -> PilotBuilder:
        """Create the PilotBuilder for turn on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)

        if ATTR_RGBWW_COLOR in kwargs:
            builder = PilotBuilder(brightness=brightness)
            rgbww = kwargs[ATTR_RGBWW_COLOR]
            builder.pilot_params.update(
                {
                    "r": rgbww[0],
                    "g": rgbww[1],
                    "b": rgbww[2],
                    "c": rgbww[3],
                    "w": rgbww[4],
                }
            )
            return builder

        if ATTR_RGBW_COLOR in kwargs:
            builder = PilotBuilder(brightness=brightness)
            rgbw = kwargs[ATTR_RGBW_COLOR]
            builder.pilot_params.update(
                {"r": rgbw[0], "g": rgbw[1], "b": rgbw[2], "w": rgbw[3]}
            )
            return builder

        color_temp = None
        if ATTR_COLOR_TEMP in kwargs:
            color_temp = color_temperature_mired_to_kelvin(kwargs[ATTR_COLOR_TEMP])

        scene_id = None
        if ATTR_EFFECT in kwargs:
            scene_id = get_id_from_scene_name(kwargs[ATTR_EFFECT])
            if scene_id == 1000:  # rhythm
                return PilotBuilder()

        _LOGGER.debug(
            "[wizlight %s] Pilot will be sent with brightness=%s, color_temp=%s, scene_id=%s",
            self._device.ip,
            brightness,
            color_temp,
            scene_id,
        )
        return PilotBuilder(brightness=brightness, colortemp=color_temp, scene=scene_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        await self._device.turn_on(self._async_pilot_builder(**kwargs))
        await self.coordinator.async_request_refresh()
