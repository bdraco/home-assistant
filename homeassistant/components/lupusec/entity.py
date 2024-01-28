"""Provides the Lupusec entity for Home Assistant."""
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, TYPE_TRANSLATION


class LupusecDevice(Entity):
    """Representation of a Lupusec device."""

    _attr_has_entity_name = True

    def __init__(self, data, device, entry_id) -> None:
        """Initialize a sensor for Lupusec device."""
        self._data = data
        self._device = device
        self._attr_unique_id = device.device_id

    def update(self):
        """Update automation state."""
        self._device.refresh()


class LupusecBaseSensor(LupusecDevice):
    """Lupusec Sensor base entity."""

    def __init__(self, data, device, entry_id) -> None:
        """Initialize the LupusecBaseSensor."""
        super().__init__(data, device, entry_id)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.name,
            manufacturer="Lupus Electronics",
            serial_number=device.device_id,
            model=TYPE_TRANSLATION.get(device.type, device.type),
            via_device=(DOMAIN, entry_id),
        )

    def get_type_name(self):
        """Return the type of the sensor."""
        return TYPE_TRANSLATION.get(self._device.type, self._device.type)
