"""The Tesla Powerwall integration."""
import asyncio
from datetime import timedelta
import logging

import requests
from tesla_powerwall import (
    APIChangedError,
    Powerwall,
    PowerwallError,
    PowerwallUnreachableError,
)
import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    POWERWALL_API_CHANGED,
    POWERWALL_API_CHARGE,
    POWERWALL_API_DEVICE_TYPE,
    POWERWALL_API_GRID_STATUS,
    POWERWALL_API_METERS,
    POWERWALL_API_SERIAL_NUMBERS,
    POWERWALL_API_SITE_INFO,
    POWERWALL_API_SITEMASTER,
    POWERWALL_API_STATUS,
    POWERWALL_COORDINATOR,
    POWERWALL_ERROR,
    POWERWALL_HTTP_SESSION,
    POWERWALL_OBJECT,
    UPDATE_INTERVAL,
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Required(CONF_IP_ADDRESS): cv.string})},
    extra=vol.ALLOW_EXTRA,
)

PLATFORMS = ["binary_sensor", "sensor"]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Tesla Powerwall component."""
    hass.data.setdefault(DOMAIN, {})
    conf = config.get(DOMAIN)

    if not conf:
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=conf,
        )
    )
    return True


async def _migrate_old_unique_ids(hass, entry_id, powerwall_data):
    serial_numbers = powerwall_data[POWERWALL_API_SERIAL_NUMBERS]
    site_info = powerwall_data[POWERWALL_API_SITE_INFO]

    @callback
    def _async_migrator(entity_entry: entity_registry.RegistryEntry):
        parts = entity_entry.unique_id.split("_")
        # Check if the unique_id starts with the serial_numbers of the powerwalls
        if parts[0 : len(serial_numbers)] != serial_numbers:
            # The old unique_id ended with the nomianal_system_engery_kWh so we can use that
            # to find the old base unique_id and extract the device_suffix.
            normalized_energy_index = (
                len(parts)
                - 1
                - parts[::-1].index(str(site_info.nominal_system_energy_kWh))
            )
            device_suffix = parts[normalized_energy_index + 1 :]

            new_unique_id = "_".join([*serial_numbers, *device_suffix])
            _LOGGER.info(
                "Migrating unique_id from [%s] to [%s]",
                entity_entry.unique_id,
                new_unique_id,
            )
            return {"new_unique_id": new_unique_id}
        return None

    await entity_registry.async_migrate_entries(hass, entry_id, _async_migrator)


async def handle_setup_error(
    hass: HomeAssistant, entry: ConfigEntry, error: PowerwallError
):
    """Log error and send notification for an error during the component setup."""
    # Only emit one notification and log the error once
    if hass.data[DOMAIN][entry.entry_id][POWERWALL_ERROR] is None:
        # Only log the error message, the full traceback is not needed
        _LOGGER.error(str(error))

        if isinstance(error, PowerwallUnreachableError):
            msg = "Could not connect to powerwall.\nSee logs for more information."
            title = "Powerwall unreachable"
        elif isinstance(error, APIChangedError):
            msg = "It seems like the API of the powerwall changed.\nPlease report this issue so it can be resolved!\nSee logs for more information."
            title = "Powerwall API changed"
        else:
            msg = "There was an error setting up the powerwall integration.\nSee logs for more information."
            title = "Powerwall setup error"

        hass.components.persistent_notification.async_create(msg, title=title)

        hass.data[DOMAIN][entry.entry_id][POWERWALL_ERROR] = error


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Tesla Powerwall from a config entry."""

    entry_id = entry.entry_id

    hass.data[DOMAIN].setdefault(entry_id, {POWERWALL_ERROR: None})
    http_session = requests.Session()
    power_wall = Powerwall(entry.data[CONF_IP_ADDRESS], http_session=http_session)
    try:
        await hass.async_add_executor_job(power_wall.detect_and_pin_version)
        powerwall_data = await hass.async_add_executor_job(call_base_info, power_wall)
    except PowerwallUnreachableError:
        http_session.close()
        raise ConfigEntryNotReady
    except PowerwallError as err:
        http_session.close()
        await handle_setup_error(hass, entry, err)
        return False

    await _migrate_old_unique_ids(hass, entry_id, powerwall_data)

    async def async_update_data():
        """Fetch data from API endpoint."""
        if hass.data[DOMAIN][entry.entry_id][POWERWALL_API_CHANGED]:
            raise UpdateFailed("Powerwall api has changed")
        try:
            return await hass.async_add_executor_job(_fetch_powerwall_data, power_wall)
        except APIChangedError as err:
            hass.data[DOMAIN][entry.entry_id][POWERWALL_API_CHANGED] = True
            await handle_setup_error(hass, entry, err)
        except PowerwallUnreachableError:
            raise UpdateFailed("Unable to fetch data from powerwall")

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Powerwall site",
        update_method=async_update_data,
        update_interval=timedelta(seconds=UPDATE_INTERVAL),
    )

    hass.data[DOMAIN][entry.entry_id] = powerwall_data
    hass.data[DOMAIN][entry.entry_id].update(
        {
            POWERWALL_OBJECT: power_wall,
            POWERWALL_COORDINATOR: coordinator,
            POWERWALL_HTTP_SESSION: http_session,
            POWERWALL_ERROR: None,
            POWERWALL_API_CHANGED: False,
        }
    )

    await coordinator.async_refresh()

    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )

    return True


def call_base_info(power_wall):
    """Wrap powerwall properties to be a callable."""
    serial_numbers = power_wall.get_serial_numbers()
    # Make sure the serial numbers always have the same order
    serial_numbers.sort()
    return {
        POWERWALL_API_SITE_INFO: power_wall.get_site_info(),
        POWERWALL_API_STATUS: power_wall.get_status(),
        POWERWALL_API_DEVICE_TYPE: power_wall.get_device_type(),
        POWERWALL_API_SERIAL_NUMBERS: serial_numbers,
    }


def _fetch_powerwall_data(power_wall):
    """Process and update powerwall data."""
    return {
        POWERWALL_API_CHARGE: power_wall.get_charge(),
        POWERWALL_API_SITEMASTER: power_wall.get_sitemaster(),
        POWERWALL_API_METERS: power_wall.get_meters(),
        POWERWALL_API_GRID_STATUS: power_wall.get_grid_status(),
    }


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )

    hass.data[DOMAIN][entry.entry_id][POWERWALL_HTTP_SESSION].close()

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
