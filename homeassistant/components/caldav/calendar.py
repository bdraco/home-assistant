"""Support for WebDav Calendar."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
import logging
import re

import voluptuous as vol

from homeassistant.components.calendar import (
    ENTITY_ID_FORMAT,
    PLATFORM_SCHEMA,
    CalendarEntity,
    CalendarEvent,
    extract_offset,
    is_offset_reached,
)
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import Throttle, dt

from .const import (
    CONF_CALENDAR,
    CONF_CALENDARS,
    CONF_CUSTOM_CALENDARS,
    CONF_DAYS,
    CONF_SEARCH,
    DOMAIN,
    OFFSET,
    PRINC_CALENDARS,
)

_LOGGER = logging.getLogger(__name__)

# Deprecated in Home Assistant 2022.8
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        # pylint: disable=no-value-for-parameter
        vol.Required(CONF_URL): vol.Url(),
        vol.Optional(CONF_CALENDARS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Inclusive(CONF_USERNAME, "authentication"): cv.string,
        vol.Inclusive(CONF_PASSWORD, "authentication"): cv.string,
        vol.Optional(CONF_CUSTOM_CALENDARS, default=[]): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required(CONF_CALENDAR): cv.string,
                        vol.Required(CONF_NAME): cv.string,
                        vol.Required(CONF_SEARCH): cv.string,
                    }
                )
            ],
        ),
        vol.Optional(CONF_VERIFY_SSL, default=True): cv.boolean,
        vol.Optional(CONF_DAYS, default=1): cv.positive_int,
    }
)

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=15)


# Deprecated in Home Assistant 2022.8
async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the WebDav Calendar platform."""
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=config,
        )
    )

    _LOGGER.warning(
        "Configuration of the Caldav integration in YAML is deprecated and "
        "will be removed in a future release; Your existing configuration "
        "has been imported into the UI automatically and can be safely removed "
        "from your configuration.yaml file"
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the WebDav Calendar entry."""
    calendars = hass.data[DOMAIN][config_entry.entry_id][PRINC_CALENDARS]
    days = config_entry.data[CONF_DAYS]

    calendar_devices = []
    for calendar in list(calendars):
        # If a calendar name was given in the configuration,
        # ignore all the others
        if (
            config_entry.options[CONF_CALENDARS]
            and calendar.name not in config_entry.options[CONF_CALENDARS]
        ):
            _LOGGER.debug("Ignoring calendar '%s'", calendar.name)
            continue

        # Create additional calendars based on custom filtering rules
        for cust_calendar in config_entry.options[CONF_CUSTOM_CALENDARS]:
            # Check that the base calendar matches
            if cust_calendar[CONF_CALENDAR] != calendar.name:
                continue

            name = cust_calendar[CONF_NAME]
            device_id = f"{cust_calendar[CONF_CALENDAR]} {cust_calendar[CONF_NAME]}"
            entity_id = generate_entity_id(ENTITY_ID_FORMAT, device_id, hass=hass)
            calendar_devices.append(
                WebDavCalendarEntity(
                    name, calendar, entity_id, days, True, cust_calendar[CONF_SEARCH]
                )
            )

        # Create a default calendar if there was no custom one
        if not config_entry.options[CONF_CUSTOM_CALENDARS]:
            name = calendar.name
            device_id = calendar.name
            entity_id = generate_entity_id(ENTITY_ID_FORMAT, device_id, hass=hass)
            calendar_devices.append(
                WebDavCalendarEntity(name, calendar, entity_id, days)
            )

    async_add_entities(calendar_devices, True)


class WebDavCalendarEntity(CalendarEntity):
    """A device for getting the next Task from a WebDav Calendar."""

    def __init__(self, name, calendar, entity_id, days, all_day=False, search=None):
        """Create the WebDav Calendar Event Device."""
        self.data = WebDavCalendarData(calendar, days, all_day, search)
        self.entity_id = entity_id
        self._event: CalendarEvent | None = None
        self._attr_name = name

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        return self._event

    async def async_get_events(self, hass, start_date, end_date):
        """Get all events in a specific time frame."""
        return await self.data.async_get_events(hass, start_date, end_date)

    def update(self):
        """Update event data."""
        self.data.update()
        event = copy.deepcopy(self.data.event)
        if event is None:
            self._event = event
            return
        (summary, offset) = extract_offset(event.summary, OFFSET)
        event.summary = summary
        self._event = event
        self._attr_extra_state_attributes = {
            "offset_reached": is_offset_reached(event.start_datetime_local, offset)
        }


class WebDavCalendarData:
    """Class to utilize the calendar dav client object to get next event."""

    def __init__(self, calendar, days, include_all_day, search):
        """Set up how we are going to search the WebDav calendar."""
        self.calendar = calendar
        self.days = days
        self.include_all_day = include_all_day
        self.search = search
        self.event = None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Get all events in a specific time frame."""
        # Get event list from the current calendar
        vevent_list = await hass.async_add_executor_job(
            self.calendar.date_search, start_date, end_date
        )
        event_list = []
        for event in vevent_list:
            if not hasattr(event.instance, "vevent"):
                _LOGGER.warning("Skipped event with missing 'vevent' property")
                continue
            vevent = event.instance.vevent
            if not self.is_matching(vevent, self.search):
                continue
            event_list.append(
                CalendarEvent(
                    summary=vevent.summary.value,
                    start=vevent.dtstart.value,
                    end=self.get_end_date(vevent),
                    location=self.get_attr_value(vevent, "location"),
                    description=self.get_attr_value(vevent, "description"),
                )
            )

        return event_list

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Get the latest data."""
        start_of_today = dt.start_of_local_day()
        start_of_tomorrow = dt.start_of_local_day() + timedelta(days=self.days)

        # We have to retrieve the results for the whole day as the server
        # won't return events that have already started
        results = self.calendar.date_search(start_of_today, start_of_tomorrow)

        # Create new events for each recurrence of an event that happens today.
        # For recurring events, some servers return the original event with recurrence rules
        # and they would not be properly parsed using their original start/end dates.
        new_events = []
        for event in results:
            if not hasattr(event.instance, "vevent"):
                _LOGGER.warning("Skipped event with missing 'vevent' property")
                continue
            vevent = event.instance.vevent
            for start_dt in vevent.getrruleset() or []:
                _start_of_today = start_of_today
                _start_of_tomorrow = start_of_tomorrow
                if self.is_all_day(vevent):
                    start_dt = start_dt.date()
                    _start_of_today = _start_of_today.date()
                    _start_of_tomorrow = _start_of_tomorrow.date()
                if _start_of_today <= start_dt < _start_of_tomorrow:
                    new_event = event.copy()
                    new_vevent = new_event.instance.vevent
                    if hasattr(new_vevent, "dtend"):
                        dur = new_vevent.dtend.value - new_vevent.dtstart.value
                        new_vevent.dtend.value = start_dt + dur
                    new_vevent.dtstart.value = start_dt
                    new_events.append(new_event)
                elif _start_of_tomorrow <= start_dt:
                    break
        vevents = [
            event.instance.vevent
            for event in results + new_events
            if hasattr(event.instance, "vevent")
        ]

        # dtstart can be a date or datetime depending if the event lasts a
        # whole day. Convert everything to datetime to be able to sort it
        vevents.sort(key=lambda x: self.to_datetime(x.dtstart.value))

        vevent = next(
            (
                vevent
                for vevent in vevents
                if (
                    self.is_matching(vevent, self.search)
                    and (not self.is_all_day(vevent) or self.include_all_day)
                    and not self.is_over(vevent)
                )
            ),
            None,
        )

        # If no matching event could be found
        if vevent is None:
            _LOGGER.debug(
                "No matching event found in the %d results for %s",
                len(vevents),
                self.calendar.name,
            )
            self.event = None
            return

        # Populate the entity attributes with the event values
        self.event = CalendarEvent(
            summary=vevent.summary.value,
            start=vevent.dtstart.value,
            end=self.get_end_date(vevent),
            location=self.get_attr_value(vevent, "location"),
            description=self.get_attr_value(vevent, "description"),
        )

    @staticmethod
    def is_matching(vevent, search):
        """Return if the event matches the filter criteria."""
        if search is None:
            return True

        pattern = re.compile(search)
        return (
            hasattr(vevent, "summary")
            and pattern.match(vevent.summary.value)
            or hasattr(vevent, "location")
            and pattern.match(vevent.location.value)
            or hasattr(vevent, "description")
            and pattern.match(vevent.description.value)
        )

    @staticmethod
    def is_all_day(vevent):
        """Return if the event last the whole day."""
        return not isinstance(vevent.dtstart.value, datetime)

    @staticmethod
    def is_over(vevent):
        """Return if the event is over."""
        return dt.now() >= WebDavCalendarData.to_datetime(
            WebDavCalendarData.get_end_date(vevent)
        )

    @staticmethod
    def to_datetime(obj):
        """Return a datetime."""
        if isinstance(obj, datetime):
            if obj.tzinfo is None:
                # floating value, not bound to any time zone in particular
                # represent same time regardless of which time zone is currently being observed
                return obj.replace(tzinfo=dt.DEFAULT_TIME_ZONE)
            return obj
        return dt.dt.datetime.combine(obj, dt.dt.time.min).replace(
            tzinfo=dt.DEFAULT_TIME_ZONE
        )

    @staticmethod
    def get_attr_value(obj, attribute):
        """Return the value of the attribute if defined."""
        if hasattr(obj, attribute):
            return getattr(obj, attribute).value
        return None

    @staticmethod
    def get_end_date(obj):
        """Return the end datetime as determined by dtend or duration."""
        if hasattr(obj, "dtend"):
            enddate = obj.dtend.value

        elif hasattr(obj, "duration"):
            enddate = obj.dtstart.value + obj.duration.value

        else:
            enddate = obj.dtstart.value + timedelta(days=1)

        return enddate
