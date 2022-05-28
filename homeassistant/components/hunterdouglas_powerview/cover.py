"""Support for hunter douglas shades."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from typing import Any

from aiopvapi.helpers.constants import (
    ATTR_POSITION1,
    ATTR_POSITION2,
    ATTR_POSITION_DATA,
)
from aiopvapi.resources.shade import (
    ATTR_POSKIND1,
    ATTR_POSKIND2,
    MAX_POSITION,
    MIN_POSITION,
    BaseShade,
    ShadeTdbu,
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
    POS_KIND_SECONDARY,
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

_LOGGER = logging.getLogger(__name__)

# Estimated time it takes to complete a transition
# from one state to another
TRANSITION_COMPLETE_DURATION = 40

PARALLEL_UPDATES = 1

RESYNC_DELAY = 60

# this equates to 0.75/100 in terms of hass blind position
# some blinds in a closed position report less than 655.35 (1%)
# but larger than 0 even though they are clearly closed
# Find 1 percent of MAX_POSITION, then find 75% of that number
# The means currently 491.5125 or less is closed position
# implemented for top/down shades, but also works fine with normal shades
CLOSED_POSITION = (0.75 / 100) * (MAX_POSITION - MIN_POSITION)


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
        # so we force a refresh when we add it if possible
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
        coordinator.data.update_shade_positions(shade.raw_data)
        room_id = shade.raw_data.get(ROOM_ID_IN_SHADE)
        room_name = room_data.get(room_id, {}).get(ROOM_NAME_UNICODE, "")
        entities.extend(
            create_powerview_shade_entity(
                coordinator, device_info, room_name, shade, name_before_refresh
            )
        )
    async_add_entities(entities)


def create_powerview_shade_entity(
    coordinator, device_info, room_name, shade, name_before_refresh
):
    """Create a PowerViewShade entity."""
    classes = []
    # order here is important as both ShadeTDBU are listed in aiovapi as can_tilt
    # and both require their own class here to work
    if isinstance(shade, ShadeTdbu):
        classes.extend([PowerViewShadeTDBUTop, PowerViewShadeTDBUBottom])
    elif isinstance(shade, Silhouette):
        classes.append(PowerViewShadeSilhouette)
    elif shade.can_tilt:
        classes.append(PowerViewShadeWithTilt)
    else:
        classes.append(PowerViewShade)
    return [
        cls(coordinator, device_info, room_name, shade, name_before_refresh)
        for cls in classes
    ]


def hd_position_to_hass(hd_position, max_val=MAX_POSITION):
    """Convert hunter douglas position to hass position."""
    return round((hd_position / max_val) * 100)


def hass_position_to_hd(hass_position, max_val=MAX_POSITION):
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
        self._attr_name = self._shade_name
        self._is_opening = False
        self._is_closing = False
        self._scheduled_transition_update = None
        if self._device_info[DEVICE_MODEL] != LEGACY_DEVICE_MODEL:
            self._attr_supported_features |= CoverEntityFeature.STOP
        self._forced_resync = None

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {STATE_ATTRIBUTE_ROOM_NAME: self._room_name}

    def set_position_primary(self, position):
        """Store position of primary shade."""
        self.data.update_shade_position(self._shade.id, position, POS_KIND_PRIMARY)

    def set_position_secondary(self, position):
        """Store position of secondary shade."""
        self.data.update_shade_position(self._shade.id, position, POS_KIND_SECONDARY)

    def set_position_vane(self, position):
        """Store position of vane."""
        self.data.update_shade_position(self._shade.id, position, POS_KIND_VANE)

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        return self.positions.primary <= CLOSED_POSITION

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
    def get_transition_steps(self):
        """Return the steps to make a move."""
        return self.current_cover_position

    async def async_close_cover(self, **kwargs):
        """Close the cover."""
        self._async_schedule_update_for_transition(self.get_transition_steps)
        self._async_update_from_command(await self._shade.close())

    async def async_open_cover(self, **kwargs):
        """Open the cover."""
        self._async_schedule_update_for_transition(100 - self.get_transition_steps)
        self._async_update_from_command(await self._shade.open())

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        # Cancel any previous updates
        self._async_cancel_scheduled_transition_update()
        self._async_update_from_command(await self._shade.stop())
        await self._async_force_refresh_state()

    @callback
    def _clamp_cover_limit(self, target_hass_position):
        """Dont allow a cover to go into an impossbile position."""
        # no override required in base
        return target_hass_position

    async def async_set_cover_position(self, **kwargs):
        """Move the shade to a specific position."""
        if ATTR_POSITION not in kwargs:
            return
        await self._async_move(self._clamp_cover_limit(kwargs[ATTR_POSITION]))

    @callback
    def _set_shade_postion(self, target_hass_position):
        position_one = hass_position_to_hd(target_hass_position)
        self.set_position_primary(position_one)
        return {
            ATTR_POSITION1: position_one,
            ATTR_POSKIND1: POS_KIND_PRIMARY,
        }

    async def _async_move(self, target_hass_position):
        """Move the shade to a position."""
        self._async_cover_transition_begin(
            self.current_cover_position, target_hass_position
        )

        self._async_update_from_command(
            await self._shade.move(self._set_shade_postion(target_hass_position))
        )

        self._async_cover_transition_complete(
            self.current_cover_position, target_hass_position
        )

    @callback
    def _async_cover_transition_begin(
        self, current_hass_position, target_hass_position
    ):
        """Calculate and schedule transition timeframe."""
        steps_to_move = abs(current_hass_position - target_hass_position)
        self._async_schedule_update_for_transition(steps_to_move)

    @callback
    def _async_cover_transition_complete(
        self, current_hass_position, target_hass_position
    ):
        """Write state back to the ha model."""
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
        self.data.update_shade_positions(shade_data)
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
        _LOGGER.debug("Force resync of shade %s", self.name)
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
            # If a transition is in progress the data will be wrong
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


class PowerViewShadeTDBU(PowerViewShade):
    """Representation of a PowerView shade with top/down bottom/up capabilities."""

    @property
    def current_cover_position_primary(self):
        """Return the current position of bottom cover."""
        return hd_position_to_hass(self.positions.primary, MAX_POSITION)

    @property
    def current_cover_position_secondary(self):
        """Return the current position of top cover."""
        return hd_position_to_hass(self.positions.secondary, MAX_POSITION)

    @property
    def get_transition_steps(self):
        """Return the steps to make a move."""
        return (
            self.current_cover_position_primary + self.current_cover_position_secondary
        )


class PowerViewShadeTDBUBottom(PowerViewShadeTDBU):
    """Representation of a top down bottom up powerview shade."""

    def __init__(self, coordinator, device_info, room_name, shade, name):
        """Initialize the shade."""
        super().__init__(coordinator, device_info, room_name, shade, name)
        self._attr_unique_id = f"{self._shade.id}_bottom"
        self._attr_name = f"{self._shade_name} Bottom"

    @callback
    def _clamp_cover_limit(self, target_hass_position):
        """Dont allow a cover to go into an impossbile position."""
        cover_top = self.current_cover_position_secondary
        target_hass_position = min(target_hass_position, (100 - cover_top))
        return target_hass_position

    @callback
    def _set_shade_postion(self, target_hass_position):
        position_bottom = hass_position_to_hd(target_hass_position)
        position_top = self.positions.secondary
        self.set_position_primary(position_bottom)
        return {
            ATTR_POSITION1: position_bottom,
            ATTR_POSITION2: position_top,
            ATTR_POSKIND1: POS_KIND_PRIMARY,
            ATTR_POSKIND2: POS_KIND_SECONDARY,
        }


class PowerViewShadeTDBUTop(PowerViewShadeTDBU):
    """Representation of a top down bottom up powerview shade."""

    def __init__(self, coordinator, device_info, room_name, shade, name):
        """Initialize the shade."""
        super().__init__(coordinator, device_info, room_name, shade, name)
        self._attr_unique_id = f"{self._shade.id}_top"
        self._attr_name = f"{self._shade_name} Top"
        self._shade.open_position = {
            ATTR_POSITION1: MIN_POSITION,
            ATTR_POSITION2: MAX_POSITION,
            ATTR_POSKIND1: POS_KIND_PRIMARY,
            ATTR_POSKIND2: POS_KIND_SECONDARY,
        }

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        # top shade needs to check other motor
        return self.positions.secondary <= CLOSED_POSITION

    @property
    def current_cover_position(self):
        """Return the current position of cover."""
        # these need to be inverted to report state correctly in HA
        return hd_position_to_hass(self.positions.secondary, MAX_POSITION)

    @callback
    def _clamp_cover_limit(self, target_hass_position):
        """Dont allow a cover to go into an impossbile position."""
        cover_bottom = self.current_cover_position_primary
        target_hass_position = min(target_hass_position, (100 - cover_bottom))
        return target_hass_position

    @callback
    def _set_shade_postion(self, target_hass_position):
        position_bottom = self.positions.primary
        position_top = hass_position_to_hd(target_hass_position)
        self.set_position_secondary(position_top)
        return {
            ATTR_POSITION1: position_bottom,
            ATTR_POSITION2: position_top,
            ATTR_POSKIND1: POS_KIND_PRIMARY,
            ATTR_POSKIND2: POS_KIND_SECONDARY,
        }


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

    @property
    def get_transition_steps(self):
        """Return the steps to make a move."""
        return hd_position_to_hass(self.positions.primary) + self._tilt_steps

    async def async_open_cover_tilt(self, **kwargs):
        """Open the cover tilt."""
        self._async_schedule_update_for_transition(100 - self.get_transition_steps)
        self._async_update_from_command(await self._shade.tilt_open())

    async def async_close_cover_tilt(self, **kwargs):
        """Close the cover tilt."""
        self._async_schedule_update_for_transition(self.get_transition_steps)
        self._async_update_from_command(await self._shade.tilt_close())

    async def async_set_cover_tilt_position(self, **kwargs):
        """Move the vane to a specific position."""
        if ATTR_TILT_POSITION not in kwargs:
            return
        await self._async_tilt(kwargs[ATTR_TILT_POSITION])

    async def _async_tilt(self, target_hass_tilt_position):
        """Move the cover tilt to a specific position."""

        self._async_cover_transition_begin(
            self.current_cover_position + self.current_cover_tilt_position,
            self.get_transition_steps,
        )

        self._async_update_from_command(
            await self._shade.move(self._set_shade_tilt(target_hass_tilt_position))
        )

    @callback
    def _set_shade_tilt(self, target_hass_position):
        """Return json for shade position requested."""
        position_vane = hass_position_to_hd(target_hass_position, self._max_tilt)
        self.set_position_primary(MIN_POSITION)
        self.set_position_vane(position_vane)
        return {
            ATTR_POSITION1: position_vane,
            ATTR_POSKIND1: POS_KIND_VANE,
        }

    @callback
    def _set_shade_postion(self, target_hass_position):
        """Return json for shade position requested."""
        position_shade = hass_position_to_hd(target_hass_position)
        self.set_position_primary(position_shade)
        self.set_position_vane(MIN_POSITION)
        return {
            ATTR_POSITION1: position_shade,
            ATTR_POSKIND1: POS_KIND_PRIMARY,
        }

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
        self._tilt_steps = 5  # 10 steps is 180° - these are 90°
