"""Support for Magic Home sensors."""
from __future__ import annotations

from datetime import date, datetime

from homeassistant import config_entries
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .coordinator import FluxLedUpdateCoordinator
from .entity import FluxEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Flux selects."""
    coordinator: FluxLedUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    device = coordinator.device
    if device.paired_remotes is not None:
        async_add_entities([FluxPairedRemotes(coordinator, entry)])


class FluxPairedRemotes(FluxEntity, SensorEntity):
    """Representation of a Flux power restore state option."""

    _attr_should_poll = False

    def __init__(
        self,
        coordinator: FluxLedUpdateCoordinator,
        entry: config_entries.ConfigEntry,
    ) -> None:
        """Initialize the power state select."""
        super().__init__(
            coordinator, entry.unique_id, f"{entry.data[CONF_NAME]} Paired Remotes"
        )
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:remote"
        if entry.unique_id:
            self._attr_unique_id = f"{entry.unique_id}_paired_remotes"

    @property
    def native_value(self) -> StateType | date | datetime:
        """Return the number of paired remotes."""
        return self._device.paired_remotes
