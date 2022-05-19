"""Support for 1-Wire entities."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from pyownet import protocol

from homeassistant.helpers.entity import DeviceInfo, Entity, EntityDescription
from homeassistant.helpers.typing import StateType

from .const import READ_MODE_BOOL, READ_MODE_INT


@dataclass
class OneWireEntityDescription(EntityDescription):
    """Class describing OneWire entities."""

    read_mode: str | None = None


_LOGGER = logging.getLogger(__name__)


class OneWireEntity(Entity):
    """Implementation of a 1-Wire entity."""

    entity_description: OneWireEntityDescription

    def __init__(
        self,
        description: OneWireEntityDescription,
        device_id: str,
        device_info: DeviceInfo,
        device_file: str,
        name: str,
        owproxy: protocol._Proxy,
    ) -> None:
        """Initialize the entity."""
        self.entity_description = description
        self._attr_unique_id = f"/{device_id}/{description.key}"
        self._attr_device_info = device_info
        self._attr_name = name
        self._device_file = device_file
        self._state: StateType = None
        self._value_raw: float | None = None
        self._owproxy = owproxy

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes of the entity."""
        return {
            "device_file": self._device_file,
            "raw_value": self._value_raw,
        }

    def _read_value(self) -> str:
        """Read a value from the server."""
        read_bytes: bytes = self._owproxy.read(self._device_file)
        return read_bytes.decode().lstrip()

    def _write_value(self, value: bytes) -> None:
        """Write a value to the server."""
        self._owproxy.write(self._device_file, value)

    def update(self) -> None:
        """Get the latest data from the device."""
        try:
            self._value_raw = float(self._read_value())
        except protocol.Error as exc:
            _LOGGER.error("Failure to read server value, got: %s", exc)
            self._state = None
        else:
            if self.entity_description.read_mode == READ_MODE_INT:
                self._state = int(self._value_raw)
            elif self.entity_description.read_mode == READ_MODE_BOOL:
                self._state = int(self._value_raw) == 1
            else:
                self._state = round(self._value_raw, 1)
