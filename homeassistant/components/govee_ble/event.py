"""Support for govee_ble event entities."""

from __future__ import annotations

from govee_ble import SensorType

from homeassistant.components.event import (
    EventDeviceClass,
    EventEntity,
    EventEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import GoveeBLEConfigEntry, format_event_dispatcher_name

BUTTON_DESCRIPTIONS = [
    EventEntityDescription(
        key=f"button_{i}",
        translation_key=f"button_{i}",
        event_types=["press"],
        device_class=EventDeviceClass.BUTTON,
    )
    for i in range(6)
]
MOTION_DESCRIPTION = EventEntityDescription(
    key="motion",
    translation_key="motion",
    event_types=["motion"],
    device_class=EventDeviceClass.MOTION,
)


class GoveeBluetoothEventEntity(EventEntity):
    """Representation of a govee ble event entity."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, address: str, description: EventEntityDescription) -> None:
        """Initialise a govee ble event entity."""
        self.entity_description = description
        # Matches logic in PassiveBluetoothProcessorEntity
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(dr.CONNECTION_BLUETOOTH, address)},
        )
        self._attr_unique_id = f"{address}-{description.key}"
        self._address = address
        self._signal = format_event_dispatcher_name(
            self._address, self.entity_description.key
        )

    async def async_added_to_hass(self) -> None:
        """Entity added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self._signal,
                self._async_handle_event,
            )
        )

    @callback
    def _async_handle_event(self) -> None:
        self._trigger_event(self.event_types[0])
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoveeBLEConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a govee ble event."""
    coordinator = entry.runtime_data
    address = coordinator.address
    sensor_type = coordinator.device_data.sensor_type
    if sensor_type is SensorType.MOTION:
        descriptions = [MOTION_DESCRIPTION]
    elif sensor_type is SensorType.BUTTON:
        button_count = coordinator.device_data.button_count
        descriptions = BUTTON_DESCRIPTIONS[0:button_count]
    else:
        return
    async_add_entities(
        GoveeBluetoothEventEntity(address, description) for description in descriptions
    )
