"""Component to make instant statistics about your history."""
from __future__ import annotations

import datetime
import logging
import math

import voluptuous as vol

from homeassistant.components.recorder import get_instance, history
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import (
    CONF_ENTITY_ID,
    CONF_NAME,
    CONF_STATE,
    CONF_TYPE,
    EVENT_HOMEASSISTANT_START,
    PERCENTAGE,
    TIME_HOURS,
)
from homeassistant.core import CoreState, Event, HomeAssistant, State, callback
from homeassistant.exceptions import TemplateError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.template import Template
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import homeassistant.util.dt as dt_util

from . import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

CONF_START = "start"
CONF_END = "end"
CONF_DURATION = "duration"
CONF_PERIOD_KEYS = [CONF_START, CONF_END, CONF_DURATION]

CONF_TYPE_TIME = "time"
CONF_TYPE_RATIO = "ratio"
CONF_TYPE_COUNT = "count"
CONF_TYPE_KEYS = [CONF_TYPE_TIME, CONF_TYPE_RATIO, CONF_TYPE_COUNT]

DEFAULT_NAME = "unnamed statistics"
UNITS: dict[str, str] = {
    CONF_TYPE_TIME: TIME_HOURS,
    CONF_TYPE_RATIO: PERCENTAGE,
    CONF_TYPE_COUNT: "",
}
ICON = "mdi:chart-line"

ATTR_VALUE = "value"


def exactly_two_period_keys(conf):
    """Ensure exactly 2 of CONF_PERIOD_KEYS are provided."""
    if sum(param in conf for param in CONF_PERIOD_KEYS) != 2:
        raise vol.Invalid(
            "You must provide exactly 2 of the following: start, end, duration"
        )
    return conf


PLATFORM_SCHEMA = vol.All(
    PLATFORM_SCHEMA.extend(
        {
            vol.Required(CONF_ENTITY_ID): cv.entity_id,
            vol.Required(CONF_STATE): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(CONF_START): cv.template,
            vol.Optional(CONF_END): cv.template,
            vol.Optional(CONF_DURATION): cv.time_period,
            vol.Optional(CONF_TYPE, default=CONF_TYPE_TIME): vol.In(CONF_TYPE_KEYS),
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        }
    ),
    exactly_two_period_keys,
)


def _floored_timestamp(incoming_dt: datetime.datetime) -> float:
    return math.floor(dt_util.as_timestamp(incoming_dt))


@callback
def async_calculate_period(
    duration: datetime.timedelta | None,
    start_template: Template | None,
    end_template: Template | None,
) -> tuple[datetime.datetime, datetime.datetime] | None:
    """Parse the templates and return the period."""
    start: datetime.datetime | None = None
    end: datetime.datetime | None = None

    # Parse start
    if start_template is not None:
        try:
            start_rendered = start_template.async_render()
        except (TemplateError, TypeError) as ex:
            HistoryStatsHelper.handle_template_exception(ex, "start")
            return None
        if isinstance(start_rendered, str):
            start = dt_util.parse_datetime(start_rendered)
        if start is None:
            try:
                start = dt_util.as_local(
                    dt_util.utc_from_timestamp(math.floor(float(start_rendered)))
                )
            except ValueError:
                _LOGGER.error("Parsing error: start must be a datetime or a timestamp")
                return None

    # Parse end
    if end_template is not None:
        try:
            end_rendered = end_template.async_render()
        except (TemplateError, TypeError) as ex:
            HistoryStatsHelper.handle_template_exception(ex, "end")
            return None
        if isinstance(end_rendered, str):
            end = dt_util.parse_datetime(end_rendered)
        if end is None:
            try:
                end = dt_util.as_local(
                    dt_util.utc_from_timestamp(math.floor(float(end_rendered)))
                )
            except ValueError:
                _LOGGER.error("Parsing error: end must be a datetime or a timestamp")
                return None

    # Calculate start or end using the duration
    if start is None:
        assert end is not None
        assert duration is not None
        start = end - duration
    if end is None:
        assert start is not None
        assert duration is not None
        end = start + duration

    return start, end


# noinspection PyUnusedLocal
async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the History Stats sensor."""
    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    entity_id: str = config[CONF_ENTITY_ID]
    entity_states: list[str] = config[CONF_STATE]
    start: Template | None = config.get(CONF_START)
    end: Template | None = config.get(CONF_END)
    duration: datetime.timedelta | None = config.get(CONF_DURATION)
    sensor_type: str = config[CONF_TYPE]
    name: str = config[CONF_NAME]

    for template in (start, end):
        if template is not None:
            template.hass = hass

    async_add_entities(
        [
            HistoryStatsSensor(
                entity_id, entity_states, start, end, duration, sensor_type, name
            )
        ]
    )


class HistoryStatsSensor(SensorEntity):
    """Representation of a HistoryStats sensor."""

    _attr_icon = ICON

    def __init__(
        self,
        entity_id: str,
        entity_states: list[str],
        start: Template | None,
        end: Template | None,
        duration: datetime.timedelta | None,
        sensor_type: str,
        name: str,
    ) -> None:
        """Initialize the HistoryStats sensor."""
        self._attr_name = name
        self._attr_native_unit_of_measurement = UNITS[sensor_type]

        self._entity_id = entity_id
        self._entity_states = set(entity_states)
        self._duration = duration
        self._start = start
        self._end = end
        self._type = sensor_type
        self._period = (datetime.datetime.min, datetime.datetime.min)

        self._history_current_period: list[State] = []
        self._previous_run_before_start = False

    @callback
    def _async_start_refresh(self, *_) -> None:
        """Register state tracking."""
        self.async_schedule_update_ha_state(True)
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._entity_id], self._async_update_from_event
            )
        )

    async def async_added_to_hass(self):
        """Create listeners when the entity is added."""
        if self.hass.state == CoreState.running:
            self._async_start_refresh()
            return
        # Delay first refresh to keep startup fast
        self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_START, self._async_start_refresh
        )

    async def async_update(self) -> None:
        """Get the latest data and updates the states."""
        await self._async_update(None)

    async def _async_update_from_event(self, event: Event) -> None:
        """Do an update and write the state if its changed."""
        await self._async_update(event)
        self.async_write_ha_state()

    async def _async_update(self, event: Event | None) -> None:
        """Process an update."""
        # Get previous values of start and end
        previous_period_start, previous_period_end = self._period
        # Parse templates
        self.update_period()
        current_period_start, current_period_end = self._period

        # Convert times to UTC
        current_period_start = dt_util.as_utc(current_period_start)
        current_period_end = dt_util.as_utc(current_period_end)
        previous_period_start = dt_util.as_utc(previous_period_start)
        previous_period_end = dt_util.as_utc(previous_period_end)

        # Compute integer timestamps
        current_period_start_timestamp = _floored_timestamp(current_period_start)
        current_period_end_timestamp = _floored_timestamp(current_period_end)
        previous_period_start_timestamp = _floored_timestamp(previous_period_start)
        previous_period_end_timestamp = _floored_timestamp(previous_period_end)
        now_timestamp = _floored_timestamp(datetime.datetime.now())

        if now_timestamp < current_period_start_timestamp:
            # History cannot tell the future
            self._history_current_period = []
            self._previous_run_before_start = True
        # If the period is the same or exapanding and it was already
        # in the start window we can accept state change events
        # instead of doing database queries
        elif (
            not self._previous_run_before_start
            and current_period_start_timestamp == previous_period_start_timestamp
            and (
                current_period_end_timestamp == previous_period_end_timestamp
                or
                # The period can expand as long as the previous period end
                # was not before now (otherwise it would miss events)
                (
                    current_period_end_timestamp >= previous_period_end_timestamp
                    and previous_period_end_timestamp <= now_timestamp
                )
            )
        ):
            # As long as the period window doesn't shrink
            # there can never be any new states in the database
            # since we would have already run the query
            # for them when the start time changed and any
            # state change events would have been appended
            new_data = False
            if event and event.data["new_state"] is not None:
                new_state: State = event.data["new_state"]
                if current_period_start <= new_state.last_changed <= current_period_end:
                    self._history_current_period.append(new_state)
                    new_data = True
            if not new_data and current_period_end_timestamp < now_timestamp:
                # If period has not changed and current time after the period end...
                # Don't compute anything as the value cannot have changed
                return
        else:
            # The period has changed, load from db
            self._history_current_period = await get_instance(
                self.hass
            ).async_add_executor_job(
                self._update_from_database,
                current_period_start,
                current_period_end,
            )
            self._previous_run_before_start = False

        if not self._history_current_period:
            self._async_set_native_value(None, None)
            return

        hours_matched, changes_to_match_state = self._async_compute_hours_and_changes(
            now_timestamp,
            current_period_start_timestamp,
            current_period_end_timestamp,
        )
        self._async_set_native_value(hours_matched, changes_to_match_state)

    def _update_from_database(
        self, start: datetime.datetime, end: datetime.datetime
    ) -> list[State]:
        return history.state_changes_during_period(
            self.hass,
            start,
            end,
            self._entity_id,
            include_start_time_state=True,
            no_attributes=True,
        ).get(self._entity_id, [])

    def _async_compute_hours_and_changes(
        self, now_timestamp: float, start_timestamp: float, end_timestamp: float
    ) -> tuple[float, int]:
        """Compute the hours matched and changes from the history list and first state."""
        # state_changes_during_period is called with include_start_time_state=True
        # which is the default and always provides the state at the start
        # of the period
        previous_state_matches = (
            self._history_current_period
            and self._history_current_period[0].state in self._entity_states
        )
        last_state_change_timestamp = start_timestamp
        elapsed = 0.0
        changes_to_match_state = 0

        # Make calculations
        for item in self._history_current_period:
            current_state_matches = item.state in self._entity_states
            state_change_timestamp = item.last_changed.timestamp()

            if previous_state_matches:
                elapsed += state_change_timestamp - last_state_change_timestamp
            elif current_state_matches:
                changes_to_match_state += 1

            previous_state_matches = current_state_matches
            last_state_change_timestamp = state_change_timestamp

        # Count time elapsed between last history state and end of measure
        if previous_state_matches:
            measure_end = min(end_timestamp, now_timestamp)
            elapsed += measure_end - last_state_change_timestamp

        # Save value in hours
        hours_matched = elapsed / 3600
        return hours_matched, changes_to_match_state

    def _async_set_native_value(
        self, hours_matched: float | None, changes_to_match_state: int | None
    ) -> None:
        """Set attrs from value and count."""
        if hours_matched is None:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        if self._type == CONF_TYPE_TIME:
            self._attr_native_value = round(hours_matched, 2)
        elif self._type == CONF_TYPE_RATIO:
            self._attr_native_value = HistoryStatsHelper.pretty_ratio(
                hours_matched, self._period
            )
        elif self._type == CONF_TYPE_COUNT:
            self._attr_native_value = changes_to_match_state
        self._attr_extra_state_attributes = {
            ATTR_VALUE: HistoryStatsHelper.pretty_duration(hours_matched)
        }

    def update_period(self) -> None:
        """Parse the templates and store a datetime tuple in _period."""
        if new_period := async_calculate_period(self._duration, self._start, self._end):
            self._period = new_period


class HistoryStatsHelper:
    """Static methods to make the HistoryStatsSensor code lighter."""

    @staticmethod
    def pretty_duration(hours):
        """Format a duration in days, hours, minutes, seconds."""
        seconds = int(3600 * hours)
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        if days > 0:
            return "%dd %dh %dm" % (days, hours, minutes)
        if hours > 0:
            return "%dh %dm" % (hours, minutes)
        return "%dm" % minutes

    @staticmethod
    def pretty_ratio(value, period):
        """Format the ratio of value / period duration."""
        if len(period) != 2 or period[0] == period[1]:
            return 0.0

        ratio = 100 * 3600 * value / (period[1] - period[0]).total_seconds()
        return round(ratio, 1)

    @staticmethod
    def handle_template_exception(ex, field):
        """Log an error nicely if the template cannot be interpreted."""
        if ex.args and ex.args[0].startswith("UndefinedError: 'None' has no attribute"):
            # Common during HA startup - so just a warning
            _LOGGER.warning(ex)
            return
        _LOGGER.error("Error parsing template for field %s", field, exc_info=ex)
