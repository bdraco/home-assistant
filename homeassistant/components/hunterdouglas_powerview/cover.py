"""Support for hunter douglas shades."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from typing import Any

from aiopvapi.helpers.constants import ATTR_POSITION1, ATTR_POSITION_DATA
from aiopvapi.resources.shade import (
    ATTR_POSKIND1,
    MAX_POSITION,
    MIN_POSITION,
    BaseShade,
    Silhouette,
    factory as PvShade,
)
import async_timeout

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import (
    COORDINATOR,
    DEVICE_INFO,
    DEVICE_MODEL,
    DOMAIN,
    LEGACY_DEVICE_MODEL,
    POS_KIND_PRIMARY,
    POS_KIND_VANE,
    PV_API,
    PV_ROOM_DATA,
    PV_SHADE_DATA,
    ROOM_ID_IN_SHADE,
    ROOM_NAME_UNICODE,
    SHADE_RESPONSE,
    STATE_ATTRIBUTE_ROOM_NAME,
)
from .coordinator import PowerviewShadeUpdateCoordinator
from .entity import ShadeEntity
from .shade_data import PowerviewShadeData, PowerviewShadePositions

_LOGGER = logging.getLogger(__name__)

# Estimated time it takes to complete a transition
# from one state to another
TRANSITION_COMPLETE_DURATION = 40

PARALLEL_UPDATES = 1

RESYNC_DELAY = 60


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the hunter douglas shades."""

    pv_data = hass.data[DOMAIN][entry.entry_id]
    room_data = pv_data[PV_ROOM_DATA]
    shade_data = pv_data[PV_SHADE_DATA]
    pv_request = pv_data[PV_API]
    coordinator: PowerviewShadeUpdateCoordinator = pv_data[COORDINATOR]
    device_info = pv_data[DEVICE_INFO]

    entities = []
    for raw_shade in shade_data.values():
        # The shade may be out of sync with the hub
        # so we force a refresh when we add it if
        # possible
        shade: BaseShade = PvShade(raw_shade, pv_request)
        name_before_refresh = shade.name
        with suppress(asyncio.TimeoutError):
            async with async_timeout.timeout(1):
                await shade.refresh()

        if ATTR_POSITION_DATA not in shade.raw_data:
            _LOGGER.info(
                "The %s shade was skipped because it is missing position data",
                name_before_refresh,
            )
            continue
        coordinator.data.update_shade(shade.raw_data)
        room_id = shade.raw_data.get(ROOM_ID_IN_SHADE)
        room_name = room_data.get(room_id, {}).get(ROOM_NAME_UNICODE, "")
        entities.append(
            create_powerview_shade_entity(
                coordinator, device_info, room_name, shade, name_before_refresh
            )
        )
    async_add_entities(entities)


def create_powerview_shade_entity(
    coordinator, device_info, room_name, shade, name_before_refresh
):
    """Create a PowerViewShade entity."""

    if isinstance(shade, Silhouette):
        return PowerViewShadeSilhouette(
            coordinator, device_info, room_name, shade, name_before_refresh
        )

    return PowerViewShade(
        coordinator, device_info, room_name, shade, name_before_refresh
    )


def hd_position_to_hass(hd_position, max_val):
    """Convert hunter douglas position to hass position."""
    return round((hd_position / max_val) * 100)


def hass_position_to_hd(hass_position, max_val):
    """Convert hass position to hunter douglas position."""
    return int(hass_position / 100 * max_val)


class PowerViewShadeBase(ShadeEntity, CoverEntity):
    """Representation of a powerview shade."""

    # The hub frequently reports stale states
    _attr_assumed_state = True
    _attr_device_class = CoverDeviceClass.SHADE

    def __init__(self, coordinator, device_info, room_name, shade, name):
        """Initialize the shade."""
        super().__init__(coordinator, device_info, room_name, shade, name)
        self._shade: BaseShade = shade
        self._is_opening = False
        self._is_closing = False
        self._scheduled_transition_update = None
        if self._device_info[DEVICE_MODEL] != LEGACY_DEVICE_MODEL:
            self._attr_supported_features |= CoverEntityFeature.STOP
        self._forced_resync = None

    @property
    def data(self) -> PowerviewShadeData:
        """Return the PowerviewShadeData."""
        return self.coordinator.data

    @property
    def positions(self) -> PowerviewShadePositions:
        """Return the PowerviewShadeData."""
        return self.coordinator.data.get_shade_positions(self._shade.id)

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {STATE_ATTRIBUTE_ROOM_NAME: self._room_name}

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        return self.positions.primary == MIN_POSITION

    @property
    def is_opening(self):
        """Return if the cover is opening."""
        return self._is_opening

    @property
    def is_closing(self):
        """Return if the cover is closing."""
        return self._is_closing

    @property
    def current_cover_position(self):
        """Return the current position of cover."""
        return hd_position_to_hass(self.positions.primary, MAX_POSITION)

    @property
    def name(self):
        """Return the name of the shade."""
        return self._shade_name

    async def async_close_cover(self, **kwargs):
        """Close the cover."""
        await self._async_move(0)

    async def async_open_cover(self, **kwargs):
        """Open the cover."""
        await self._async_move(100)

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        # Cancel any previous updates
        self._async_cancel_scheduled_transition_update()
        self._async_update_from_command(await self._shade.stop())
        await self._async_force_refresh_state()

    async def async_set_cover_position(self, **kwargs):
        """Move the shade to a specific position."""
        if ATTR_POSITION not in kwargs:
            return
        await self._async_move(kwargs[ATTR_POSITION])

    async def _async_move(self, target_hass_position):
        """Move the shade to a position."""
        current_hass_position = hd_position_to_hass(
            self.positions.primary, MAX_POSITION
        )
        steps_to_move = abs(current_hass_position - target_hass_position)
        self._async_schedule_update_for_transition(steps_to_move)
        self._async_update_from_command(
            await self._shade.move(
                {
                    ATTR_POSITION1: hass_position_to_hd(
                        target_hass_position, MAX_POSITION
                    ),
                    ATTR_POSKIND1: POS_KIND_PRIMARY,
                }
            )
        )
        self._is_opening = False
        self._is_closing = False
        if target_hass_position > current_hass_position:
            self._is_opening = True
        elif target_hass_position < current_hass_position:
            self._is_closing = True
        self.async_write_ha_state()

    @callback
    def _async_update_from_command(self, raw_data: dict[str | int, Any] | None) -> None:
        """Update the shade state after a command."""
        if raw_data and (shade_data := raw_data.get(SHADE_RESPONSE)):
            self._async_update_shade_data(shade_data)

    @callback
    def _async_update_shade_data(self, shade_data: dict[str | int, Any]) -> None:
        """Update the current cover position from the data."""
        _LOGGER.debug("Raw data update: %s", shade_data)
        self.data.update_shade(shade_data)
        self._is_opening = False
        self._is_closing = False

    @callback
    def _async_cancel_scheduled_transition_update(self):
        """Cancel any previous updates."""
        if self._scheduled_transition_update:
            self._scheduled_transition_update()
            self._scheduled_transition_update = None
        if self._forced_resync:
            self._forced_resync()
            self._forced_resync = None

    @callback
    def _async_schedule_update_for_transition(self, steps):
        self.async_write_ha_state()

        # Cancel any previous updates
        self._async_cancel_scheduled_transition_update()

        est_time_to_complete_transition = 1 + int(
            TRANSITION_COMPLETE_DURATION * (steps / 100)
        )

        _LOGGER.debug(
            "Estimated time to complete transition of %s steps for %s: %s",
            steps,
            self.name,
            est_time_to_complete_transition,
        )

        # Schedule an update for when we expect the transition
        # to be completed.
        self._scheduled_transition_update = async_call_later(
            self.hass,
            est_time_to_complete_transition,
            self._async_complete_schedule_update,
        )

    async def _async_complete_schedule_update(self, _):
        """Update status of the cover."""
        _LOGGER.debug("Processing scheduled update for %s", self.name)
        self._scheduled_transition_update = None
        await self._async_force_refresh_state()
        self._forced_resync = async_call_later(
            self.hass, RESYNC_DELAY, self._async_force_resync
        )

    async def _async_force_resync(self, *_):
        """Force a resync after an update since the hub may have stale state."""
        self._forced_resync = None
        await self._async_force_refresh_state()

    async def _async_force_refresh_state(self):
        """Refresh the cover state and force the device cache to be bypassed."""
        await self._shade.refresh()
        self._async_update_shade_data(self._shade.raw_data)
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._async_update_shade_from_group)
        )

    async def async_will_remove_from_hass(self):
        """Cancel any pending refreshes."""
        self._async_cancel_scheduled_transition_update()

    @callback
    def _async_update_shade_from_group(self):
        """Update with new data from the coordinator."""
        if self._scheduled_transition_update or self._forced_resync:
            # If a transition in in progress
            # the data will be wrong
            return
        self.data.update_from_group_data(self._shade.id)
        self.async_write_ha_state()


class PowerViewShade(PowerViewShadeBase):
    """Represent a standard shade."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
    )


class PowerViewShadeWithTilt(PowerViewShade):
    """Representation of a PowerView shade with tilt capabilities."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.OPEN_TILT
        | CoverEntityFeature.CLOSE_TILT
        | CoverEntityFeature.STOP_TILT
        | CoverEntityFeature.SET_TILT_POSITION
    )

    _max_tilt = MAX_POSITION
    _tilt_steps = 10

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the current cover tile position."""
        return hd_position_to_hass(self.positions.vane, self._max_tilt)

    async def async_open_cover_tilt(self, **kwargs):
        """Open the cover tilt."""
        current_hass_position = hd_position_to_hass(
            self.positions.primary, MAX_POSITION
        )
        steps_to_move = current_hass_position + self._tilt_steps
        self._async_schedule_update_for_transition(steps_to_move)
        self._async_update_from_command(await self._shade.tilt_open())

    async def async_close_cover_tilt(self, **kwargs):
        """Close the cover tilt."""
        current_hass_position = hd_position_to_hass(
            self.positions.primary, MAX_POSITION
        )
        steps_to_move = current_hass_position + self._tilt_steps
        self._async_schedule_update_for_transition(steps_to_move)
        self._async_update_from_command(await self._shade.tilt_close())

    async def async_set_cover_tilt_position(self, **kwargs):
        """Move the cover tilt to a specific position."""
        target_hass_tilt_position = kwargs[ATTR_TILT_POSITION]
        current_hass_position = hd_position_to_hass(
            self.positions.primary, MAX_POSITION
        )
        steps_to_move = current_hass_position + self._tilt_steps

        self._async_schedule_update_for_transition(steps_to_move)
        self._async_update_from_command(
            await self._shade.move(
                {
                    ATTR_POSITION1: hass_position_to_hd(
                        target_hass_tilt_position, self._max_tilt
                    ),
                    ATTR_POSKIND1: POS_KIND_VANE,
                }
            )
        )

    async def async_stop_cover_tilt(self, **kwargs):
        """Stop the cover tilting."""
        # Cancel any previous updates
        await self.async_stop_cover()


class PowerViewShadeSilhouette(PowerViewShadeWithTilt):
    """Representation of a Silhouette PowerView shade."""

    def __init__(self, coordinator, device_info, room_name, shade, name):
        """Initialize the shade."""
        super().__init__(coordinator, device_info, room_name, shade, name)
        self._max_tilt = 32767
        self._tilt_steps = 4
