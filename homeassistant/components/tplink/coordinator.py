"""Component to embed TP-Link smart home devices."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from kasa import SmartDevice, SmartDeviceException

from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

REQUEST_REFRESH_DELAY = 0.35


def _internal_state_without_time(internal_state: dict[str, Any]) -> dict[str, Any]:
    """Return the internal state without time."""
    state_copy = internal_state.copy()
    state_copy.pop("time", None)
    return state_copy


class TPLinkDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """DataUpdateCoordinator to gather data for a specific TPLink device."""

    def __init__(
        self,
        hass: HomeAssistant,
        device: SmartDevice,
    ) -> None:
        """Initialize DataUpdateCoordinator to gather data for specific SmartPlug."""
        self.device = device
        self.update_children = True
        update_interval = timedelta(seconds=5)
        super().__init__(
            hass,
            _LOGGER,
            name=device.host,
            update_interval=update_interval,
            # We don't want an immediate refresh since the device
            # takes a moment to reflect the state change
            request_refresh_debouncer=Debouncer(
                hass, _LOGGER, cooldown=REQUEST_REFRESH_DELAY, immediate=False
            ),
            always_update=False,
        )

    async def async_request_refresh_without_children(self) -> None:
        """Request a refresh without the children."""
        # If the children do get updated this is ok as this is an
        # optimization to reduce the number of requests on the device
        # when we do not need it.
        self.update_children = False
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all device and sensor data from api."""
        device = self.device
        try:
            await device.update(update_children=self.update_children)
            return _internal_state_without_time(device.internal_state)
        except SmartDeviceException as ex:
            raise UpdateFailed(ex) from ex
        finally:
            self.update_children = True
