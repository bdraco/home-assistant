"""Google config for Cloud."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import get_device_class

from .const import DOMAIN as CLOUD_DOMAIN

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

CLOUD_GOOGLE = f"{CLOUD_DOMAIN}.google_assistant"


SUPPORTED_DOMAINS = {
    "alarm_control_panel",
    "button",
    "camera",
    "climate",
    "cover",
    "fan",
    "group",
    "humidifier",
    "input_boolean",
    "input_button",
    "input_select",
    "light",
    "lock",
    "media_player",
    "scene",
    "script",
    "select",
    "switch",
    "vacuum",
}

SUPPORTED_BINARY_SENSOR_DEVICE_CLASSES = {
    BinarySensorDeviceClass.DOOR,
    BinarySensorDeviceClass.GARAGE_DOOR,
    BinarySensorDeviceClass.LOCK,
    BinarySensorDeviceClass.MOTION,
    BinarySensorDeviceClass.OPENING,
    BinarySensorDeviceClass.PRESENCE,
    BinarySensorDeviceClass.WINDOW,
}

SUPPORTED_SENSOR_DEVICE_CLASSES = {
    SensorDeviceClass.AQI,
    SensorDeviceClass.CO,
    SensorDeviceClass.CO2,
    SensorDeviceClass.HUMIDITY,
    SensorDeviceClass.PM10,
    SensorDeviceClass.PM25,
    SensorDeviceClass.TEMPERATURE,
    SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
}


def _supported_legacy(hass: HomeAssistant, entity_id: str) -> bool:
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
