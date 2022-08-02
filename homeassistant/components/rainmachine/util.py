"""Define RainMachine utilities."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any


from homeassistant.backports.enum import StrEnum
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import COORDINATOR_UPDATE_INTERVAL_MAP, LOGGER

SIGNAL_REBOOT_COMPLETED = "rainmachine_reboot_completed_{0}"
SIGNAL_REBOOT_REQUESTED = "rainmachine_reboot_requested_{0}"


class RunStates(StrEnum):
    """Define an enum for program/zone run states."""

    NOT_RUNNING = "Not Running"
    QUEUED = "Queued"
    RUNNING = "Running"


RUN_STATE_MAP = {
    0: RunStates.NOT_RUNNING,
    1: RunStates.RUNNING,
    2: RunStates.QUEUED,
}


def key_exists(data: dict[str, Any], search_key: str) -> bool:
    """Return whether a key exists in a nested dict."""
    for key, value in data.items():
        if key == search_key:
            return True
        if isinstance(value, dict):
            return key_exists(value, search_key)
    return False


class RainMachineDataUpdateCoordinator(DataUpdateCoordinator[dict]):
    """Define an extended DataUpdateCoordinator."""

    _api_category_with_shortest_interval = min(
        COORDINATOR_UPDATE_INTERVAL_MAP,
        key=COORDINATOR_UPDATE_INTERVAL_MAP.get,  # type: ignore[arg-type]
    )

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry: ConfigEntry,
        name: str,
        api_category: str,
        update_interval: timedelta,
        update_method: Callable[..., Awaitable],
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            LOGGER,
            name=name,
            update_interval=update_interval,
            update_method=update_method,
        )

        # RainMachine coordinators have different update intervals based on how
        # frequently their data is needed. We label the one with the shortest interval
        # as the "reboot watcher" (i.e., the coordinator who is responsible for
        # notifying others when a reboot has been completed):
        if api_category == self._api_category_with_shortest_interval:
            self._reboot_watcher = True
        else:
            self._reboot_watcher = False

        self._rebooting = False
        self._signal_handler_unsubs: list[Callable[..., None]] = []
        self.config_entry = entry
        self.signal_reboot_completed = SIGNAL_REBOOT_COMPLETED.format(
            self.config_entry.entry_id
        )
        self.signal_reboot_requested = SIGNAL_REBOOT_REQUESTED.format(
            self.config_entry.entry_id
        )

    async def async_initialize(self) -> None:
        """Initialize the coordinator."""

        @callback
        def async_reboot_completed() -> None:
            """Respond to a reboot completed notification."""
            self._rebooting = False
            self.last_update_success = True
            self.async_update_listeners()

        @callback
        def async_reboot_requested() -> None:
            """Respond to a reboot request."""
            self._rebooting = True
            self.last_update_success = False
            self.async_update_listeners()

        for signal, func in (
            (self.signal_reboot_completed, async_reboot_completed),
            (self.signal_reboot_requested, async_reboot_requested),
        ):
            self._signal_handler_unsubs.append(
                async_dispatcher_connect(self.hass, signal, func)
            )

        @callback
        def async_check_reboot_complete() -> None:
            """Check whether an active reboot has been completed."""
            if self._rebooting and self.last_update_success:
                async_dispatcher_send(self.hass, self.signal_reboot_completed)

        if self._reboot_watcher:
            self.async_add_listener(async_check_reboot_complete)

        @callback
        def async_teardown() -> None:
            """Tear the coordinator down appropriately."""
            for unsub in self._signal_handler_unsubs:
                unsub()

        self.config_entry.async_on_unload(async_teardown)
