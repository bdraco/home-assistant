"""The Garmin Connect integration."""
import asyncio
from datetime import date, timedelta
import logging

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.util import Throttle

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]
MIN_SCAN_INTERVAL = timedelta(minutes=10)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Garmin Connect from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    garmin_client = Garmin(username, password)

    try:
        await hass.async_add_executor_job(garmin_client.login)
    except (
        GarminConnectAuthenticationError,
        GarminConnectTooManyRequestsError,
    ) as err:
        _LOGGER.error("Error occurred during Garmin Connect login request: %s", err)
        return False
    except (GarminConnectConnectionError) as err:
        _LOGGER.error(
            "Connection error occurred during Garmin Connect login request: %s", err
        )
        raise ConfigEntryNotReady from err
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception("Unknown error occurred during Garmin Connect login request")
        return False

    garmin_data = GarminConnectData(hass, garmin_client)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = garmin_data

    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class GarminConnectData:
    """Define an object to hold sensor data."""

    def __init__(self, hass, client):
        """Initialize."""
        self.hass = hass
        self.client = client
        self.data = None

    async def _get_combined_alarms_of_all_devices(self):
        """Combine the list of active alarms from all garmin devices."""
        alarms = []
        devices = await self.hass.async_add_executor_job(self.client.get_devices)
        for device in devices:
            device_settings = await self.hass.async_add_executor_job(
                self.client.get_device_settings, device["deviceId"]
            )
            alarms += device_settings["alarms"]
        return alarms

    @Throttle(MIN_SCAN_INTERVAL)
    async def async_update(self):
        """Update data via library."""
        today = date.today()

        try:
            self.data = await self.hass.async_add_executor_job(
                self.client.get_stats_and_body, today.isoformat()
            )
            self.data["nextAlarm"] = await self._get_combined_alarms_of_all_devices()
        except (
            GarminConnectAuthenticationError,
            GarminConnectTooManyRequestsError,
            GarminConnectConnectionError,
        ) as err:
            _LOGGER.error(
                "Error occurred during Garmin Connect get activity request: %s", err
            )
            return
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception(
                "Unknown error occurred during Garmin Connect get activity request"
            )
            return
