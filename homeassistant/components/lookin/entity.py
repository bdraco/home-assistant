"""The lookin integration entity."""
from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .aiolookin import POWER_CMD, POWER_OFF_CMD, POWER_ON_CMD, Climate, Remote
from .const import DOMAIN
from .models import LookinData


class LookinEntity(Entity):
    """A base class for lookin entities."""

    def __init__(
        self,
        uuid: str,
        device: Remote | Climate,
        lookin_data: LookinData,
    ) -> None:
        """Init the base entity."""
        self._device = device
        self._uuid = uuid
        self._lookin_device = lookin_data.lookin_device
        self._lookin_protocol = lookin_data.lookin_protocol
        self._lookin_udp_subs = lookin_data.lookin_udp_subs
        self._meteo_coordinator = lookin_data.meteo_coordinator
        self._attr_unique_id = uuid
        self._attr_name = self._device.name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._uuid)},
            "name": self._device.name,
            "model": self._device.device_type,
            "via_device": (DOMAIN, self._lookin_device.id),
        }


class LookinPowerEntity(LookinEntity):
    """A Lookin entity that has a power on and power off command."""

    def __init__(
        self,
        uuid: str,
        device: Remote | Climate,
        lookin_data: LookinData,
    ) -> None:
        """Init the power entity."""
        super().__init__(uuid, device, lookin_data)
        self._power_on_command: str = POWER_CMD
        self._power_off_command: str = POWER_CMD
        function_names = {function.name for function in self._device.functions}
        if POWER_ON_CMD in function_names:
            self._power_on_command = POWER_ON_CMD
        if POWER_OFF_CMD in function_names:
            self._power_off_command = POWER_OFF_CMD
