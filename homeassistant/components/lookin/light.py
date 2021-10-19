"""The lookin integration light platform."""
from __future__ import annotations

from typing import Any

from aiolookin import Remote

from homeassistant.components.light import COLOR_MODE_ONOFF, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import LookinPowerEntity
from .models import LookinData


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the light platform for lookin from a config entry."""
    lookin_data: LookinData = hass.data[DOMAIN][config_entry.entry_id]
    entities = []

    for remote in lookin_data.devices:
        if remote["Type"] != "03":
            continue
        uuid = remote["UUID"]
        device = await lookin_data.lookin_protocol.get_remote(uuid)
        entities.append(
            LookinLightEntity(
                uuid=uuid,
                device=device,
                lookin_data=lookin_data,
            )
        )

    async_add_entities(entities)


class LookinLightEntity(LookinPowerEntity, LightEntity):
    """A lookin IR controlled light."""

    _attr_supported_color_modes = {COLOR_MODE_ONOFF}
    _attr_color_mode = COLOR_MODE_ONOFF

    def __init__(
        self,
        uuid: str,
        device: Remote,
        lookin_data: LookinData,
    ) -> None:
        """Init the light."""
        super().__init__(uuid, device, lookin_data)
        self._attr_is_on = False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        await self._async_send_command(self._power_on_command)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self._async_send_command(self._power_off_command)
        self._attr_is_on = False
        self.async_write_ha_state()
