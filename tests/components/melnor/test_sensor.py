"""Test the Melnor sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.helpers import entity_registry

from .conftest import (
    mock_config_entry,
    mock_melnor_device,
    patch_async_ble_device_from_address,
    patch_async_register_callback,
    patch_melnor_device,
)


async def test_battery_sensor(hass):
    """Test the battery sensor."""

    entry = mock_config_entry(hass)

    with patch_async_ble_device_from_address(), patch_melnor_device(), patch_async_register_callback():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        battery_sensor = hass.states.get("sensor.test_melnor_battery")
        assert battery_sensor.state == "80"
        assert battery_sensor.attributes["unit_of_measurement"] == PERCENTAGE
        assert battery_sensor.attributes["device_class"] == SensorDeviceClass.BATTERY
        assert battery_sensor.attributes["state_class"] == SensorStateClass.MEASUREMENT


async def test_rssi_sensor(hass):
    """Test the rssi sensor."""

    entry = mock_config_entry(hass)

    device = mock_melnor_device()

    with patch_async_ble_device_from_address(), patch_melnor_device(
        device
    ), patch_async_register_callback():
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity_id = f"sensor.{device.name}_rssi"

        # Ensure the entity is disabled by default by checking the registry
        ent_registry = entity_registry.async_get(hass)

        rssi_registry_entry = ent_registry.async_get(entity_id)

        assert rssi_registry_entry is not None
        assert rssi_registry_entry.disabled_by is not None

        # Enable the entity and assert everything else is working as expected
        ent_registry.async_update_entity(entity_id, disabled_by=None)

        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        rssi = hass.states.get(entity_id)

        assert (
            rssi.attributes["unit_of_measurement"] == SIGNAL_STRENGTH_DECIBELS_MILLIWATT
        )
        assert rssi.attributes["device_class"] == SensorDeviceClass.SIGNAL_STRENGTH
        assert rssi.attributes["state_class"] == SensorStateClass.MEASUREMENT
