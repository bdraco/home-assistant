"""Alexa configuration for Home Assistant Cloud."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta
from http import HTTPStatus
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
from hass_nabucasa import Cloud, cloud_api
from yarl import URL

from homeassistant.components import persistent_notification
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.homeassistant.exposed_entities import (
    async_expose_entity,
    async_get_assistant_settings,
    async_listen_entity_updates,
    async_should_expose,
)
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import CLOUD_NEVER_EXPOSED_ENTITIES
from homeassistant.core import Event, HomeAssistant, callback, split_entity_id
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, start
from homeassistant.helpers.entity import get_device_class
from homeassistant.helpers.entityfilter import EntityFilter
from homeassistant.helpers.event import async_call_later
from homeassistant.setup import async_setup_component
from homeassistant.util.dt import utcnow

from .const import (
    CONF_ENTITY_CONFIG,
    CONF_FILTER,
    DOMAIN as CLOUD_DOMAIN,
    PREF_ALEXA_REPORT_STATE,
    PREF_ENABLE_ALEXA,
    PREF_SHOULD_EXPOSE,
)
from .prefs import ALEXA_SETTINGS_VERSION, CloudPreferences

if TYPE_CHECKING:
    from .client import CloudClient

_LOGGER = logging.getLogger(__name__)

CLOUD_ALEXA = f"{CLOUD_DOMAIN}.alexa"

# Time to wait when entity preferences have changed before syncing it to
# the cloud.
SYNC_DELAY = 1


SUPPORTED_DOMAINS = {
    "alarm_control_panel",
    "alert",
    "automation",
    "button",
    "camera",
    "climate",
    "cover",
    "fan",
    "group",
    "humidifier",
    "image_processing",
    "input_boolean",
    "input_button",
    "input_number",
    "light",
    "lock",
    "media_player",
    "number",
    "scene",
    "script",
    "switch",
    "timer",
    "vacuum",
}

SUPPORTED_BINARY_SENSOR_DEVICE_CLASSES = {
    BinarySensorDeviceClass.DOOR,
    BinarySensorDeviceClass.GARAGE_DOOR,
    BinarySensorDeviceClass.MOTION,
    BinarySensorDeviceClass.OPENING,
    BinarySensorDeviceClass.PRESENCE,
    BinarySensorDeviceClass.WINDOW,
}

SUPPORTED_SENSOR_DEVICE_CLASSES = {
    SensorDeviceClass.TEMPERATURE,
}


def entity_supported(hass: HomeAssistant, entity_id: str) -> bool:
    """Return if the entity is supported.

    This is called when migrating from legacy config format to avoid exposing
    all binary sensors and sensors.
    """
    domain = split_entity_id(entity_id)[0]
    if domain in SUPPORTED_DOMAINS:
        return True

    try:
        device_class = get_device_class(hass, entity_id)
    except HomeAssistantError:
        # The entity no longer exists
        return False
    if (
        domain == "binary_sensor"
        and device_class in SUPPORTED_BINARY_SENSOR_DEVICE_CLASSES
    ):
        return True

    if domain == "sensor" and device_class in SUPPORTED_SENSOR_DEVICE_CLASSES:
        return True

    return False
