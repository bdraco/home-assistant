"""Support for sensorpush ble sensors."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothDataUpdateCoordinator,
)
from homeassistant.components.bluetooth.sensor import BluetoothSensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SensorPush BLE sensors."""
    coordinator: BluetoothDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entry.async_on_unload(
        coordinator.async_add_entities_listener(
            BluetoothSensorEntity, async_add_entities
        )
    )
