"""Support for TPLink Fan devices."""

import logging
import math
from typing import Any

from kasa import Device, Module
from kasa.interfaces import Fan

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)
from homeassistant.util.scaling import int_states_in_range

from . import legacy_device_id
from .const import DOMAIN
from .coordinator import TPLinkDataUpdateCoordinator
from .entity import CoordinatedTPLinkEntity, async_refresh_after
from .models import TPLinkData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up fans."""
    data: TPLinkData = hass.data[DOMAIN][config_entry.entry_id]
    parent_coordinator = data.parent_coordinator
    device = parent_coordinator.device
    entities: list = []
    if Module.Fan in device.modules:
        entities.append(
            TPLinkFan(device, parent_coordinator, device.modules[Module.Fan])
        )
    entities.extend(
        TPLinkFan(child, parent_coordinator, child.modules[Module.Fan], parent=device)
        for child in device.children
        if Module.Fan in child.modules
    )
    async_add_entities(entities)


SPEED_RANGE = (1, 4)  # off is not included


class TPLinkFan(CoordinatedTPLinkEntity, FanEntity):
    """Representation of a fan for a TPLink Fan device."""

    _attr_speed_count = int_states_in_range(SPEED_RANGE)
    _attr_supported_features = FanEntityFeature.SET_SPEED
    _attr_name = None

    def __init__(
        self,
        device: Device,
        coordinator: TPLinkDataUpdateCoordinator,
        fan_module: Fan,
        parent: Device | None = None,
    ) -> None:
        """Initialize the fan."""
        self.fan_module = fan_module
        self._attr_unique_id = legacy_device_id(device)
        super().__init__(device, coordinator, parent=parent)
        self._async_update_attrs()

    @async_refresh_after
    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        if percentage is not None:
            value_in_range = math.ceil(
                percentage_to_ranged_value(SPEED_RANGE, percentage)
            )
        else:
            value_in_range = SPEED_RANGE[1]
        await self.fan_module.set_fan_speed_level(value_in_range)

    @async_refresh_after
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        await self.fan_module.set_fan_speed_level(0)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        value_in_range = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
        await self.fan_module.set_fan_speed_level(value_in_range)

    @callback
    def _async_update_attrs(self) -> None:
        """Update the entity's attributes."""
        fan_speed = self.fan_module.fan_speed_level
        self._attr_is_on = fan_speed != 0
        if self._attr_is_on:
            self._attr_percentage = ranged_value_to_percentage(SPEED_RANGE, fan_speed)
        else:
            self._attr_percentage = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._async_update_attrs()
        super()._handle_coordinator_update()
