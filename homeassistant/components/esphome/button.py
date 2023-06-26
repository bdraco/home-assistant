"""Support for ESPHome buttons."""
from __future__ import annotations

from aioesphomeapi import ButtonInfo, EntityInfo, EntityState

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.enum import try_parse_enum

from .entity import (
    EsphomeEntity,
    platform_async_setup_entry,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up ESPHome buttons based on a config entry."""
    await platform_async_setup_entry(
        hass,
        entry,
        async_add_entities,
        info_type=ButtonInfo,
        entity_type=EsphomeButton,
        state_type=EntityState,
    )


class EsphomeButton(EsphomeEntity[ButtonInfo, EntityState], ButtonEntity):
    """A button implementation for ESPHome."""

    @callback
    def _on_static_info_update(self, static_info: EntityInfo) -> None:
        """Set attrs from static info."""
        super()._on_static_info_update(static_info)
        self._attr_device_class = try_parse_enum(
            ButtonDeviceClass, self._static_info.device_class
        )

    @callback
    def _on_device_update(self) -> None:
        """Call when device updates or entry data changes."""
        self._on_entry_data_changed()

    async def async_press(self) -> None:
        """Press the button."""
        await self._client.button_command(self._key)
