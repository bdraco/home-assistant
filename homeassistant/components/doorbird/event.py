"""Support for doorbird events."""

from dataclasses import dataclass

from homeassistant.components.event import (
    EventDeviceClass,
    EventEntity,
    EventEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import DoorbirdEvent
from .entity import DoorBirdEntity
from .models import DoorBirdData


@dataclass(kw_only=True, frozen=True)
class DoorBirdEventEntityDescription(EventEntityDescription):
    """Describes a DoorBird event entity."""

    event_type: str


EVENT_DESCRIPTIONS = {
    "doorbell": DoorBirdEventEntityDescription(
        key="doorbell",
        translation_key="doorbell",
        device_class=EventDeviceClass.DOORBELL,
        event_type="ring",
    ),
    "motion": DoorBirdEventEntityDescription(
        key="motion",
        translation_key="motion",
        device_class=EventDeviceClass.MOTION,
        event_type="motion",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the DoorBird event platform."""
    config_entry_id = config_entry.entry_id
    door_bird_data: DoorBirdData = hass.data[DOMAIN][config_entry_id]
    async_add_entities(
        DoorBirdEventEntity(
            door_bird_data,
            doorbird_event,
            EVENT_DESCRIPTIONS[doorbird_event.event_type],
        )
        for doorbird_event in door_bird_data.door_station.event_descriptions
        if doorbird_event.event_type in EVENT_DESCRIPTIONS
    )


class DoorBirdEventEntity(DoorBirdEntity, EventEntity):
    """A relay in a DoorBird device."""

    entity_description: DoorBirdEventEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        door_bird_data: DoorBirdData,
        doorbird_event: DoorbirdEvent,
        entity_description: DoorBirdEventEntityDescription,
    ) -> None:
        """Initialize an event for a doorbird device."""
        super().__init__(door_bird_data)
        self._doorbird_event = doorbird_event
        self.entity_description = entity_description
        self._attr_unique_id = f"{self._mac_addr}_{doorbird_event.event}"
        self._attr_name = doorbird_event.event.title()

    async def async_added_to_hass(self) -> None:
        """Subscribe to device events."""
        self.async_on_remove(
            self.hass.bus.async_listen(
                f"{DOMAIN}_{self._doorbird_event.event}",
                self._async_handle_event,
            )
        )

    @callback
    def _async_handle_event(self, event: Event) -> None:
        """Handle a device event."""
        self._trigger_event(event_type=self.entity_description.event_type)
        self.async_write_ha_state()
