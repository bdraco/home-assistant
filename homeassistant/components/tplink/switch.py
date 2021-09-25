"""Support for TPLink HS100/HS110/HS200 smart switch."""
from __future__ import annotations

from asyncio import sleep
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.components.tplink import TPLinkDataUpdateCoordinator
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .common import CoordinatedTPLinkEntity
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches."""
    coordinator: TPLinkDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    device = coordinator.device
    if not device.is_plug and not device.is_strip:
        return
    entities = []
    entities.append(SmartPlugSwitch(device, coordinator))
    if device.is_strip:
        _LOGGER.debug("Initializing strip with %s sockets", len(device.children))
        for child in device.children:
            device.append(SmartPlugSwitch(child, coordinator))

    async_add_entities(entities)


class SmartPlugSwitch(CoordinatedTPLinkEntity, SwitchEntity):
    """Representation of a TPLink Smart Plug switch."""

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.device.turn_on()
        await self._async_device_workarounds()
        await self._async_refresh_with_children()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.device.turn_off()
        await self._async_device_workarounds()
        await self._async_refresh_with_children()

    async def _async_device_workarounds(self) -> None:
        # Workaround for delayed device state update on HS210: #55190
        if "HS210" in self.device.model:
            await sleep(0.5)

    async def _async_refresh_with_children(self) -> None:
        self.coordinator.update_children = False
        await self.coordinator.async_refresh()
