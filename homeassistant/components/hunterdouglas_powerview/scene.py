"""Support for Powerview scenes from a Powerview hub."""
import logging
from typing import Any

from aiopvapi.resources.scene import Scene as PvScene
import voluptuous as vol

from homeassistant.components.scene import Scene
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_PLATFORM
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    HUB_ADDRESS,
    PV_API,
    PV_ROOM_DATA,
    PV_SCENE_DATA,
    ROOM_NAME,
    SCENE_DATA,
    STATE_ATTRIBUTE_ROOM_NAME,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = vol.Schema(
    {vol.Required(CONF_PLATFORM): DOMAIN, vol.Required(HUB_ADDRESS): cv.string}
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Import platform from yaml."""

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=config
        )
    )


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up powerview scene entries."""

    pv_data = hass.data[DOMAIN][entry.entry_id]
    room_data = pv_data[PV_ROOM_DATA]
    scene_data = pv_data[PV_SCENE_DATA]
    pv_request = pv_data[PV_API]

    pvscenes = (
        PowerViewScene(hass, PvScene(raw_scene, pv_request), room_data)
        for scene_id, raw_scene in scene_data[SCENE_DATA].items()
    )
    async_add_entities(pvscenes)


class PowerViewScene(Scene):
    """Representation of a Powerview scene."""

    def __init__(self, hass, scene, room_data):
        """Initialize the scene."""
        self._scene = scene
        self.hass = hass
        self._room_name = room_data.get(scene.room_id, {}).get(ROOM_NAME, "")

    @property
    def name(self):
        """Return the name of the scene."""
        return self._scene.name

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {STATE_ATTRIBUTE_ROOM_NAME: self._room_name}

    @property
    def icon(self):
        """Icon to use in the frontend."""
        return "mdi:blinds"

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate scene. Try to get entities into requested state."""
        await self._scene.activate()
