"""Support for Switchbot devices."""
# pylint: disable=import-error
import switchbot

from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_RETRY_COUNT,
    CONF_RETRY_TIMEOUT,
    CONF_SCAN_TIMEOUT,
    CONF_TIME_BETWEEN_UPDATE_COMMAND,
    DATA_COORDINATOR,
    DATA_UNDO_UPDATE_LISTENER,
    DEFAULT_RETRY_COUNT,
    DEFAULT_RETRY_TIMEOUT,
    DEFAULT_SCAN_TIMEOUT,
    DEFAULT_TIME_BETWEEN_UPDATE_COMMAND,
    DOMAIN,
)
from .coordinator import SwitchbotDataUpdateCoordinator

PLATFORMS = ["switch"]


async def async_setup_entry(hass, entry):
    """Set up Switchbot from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    if not entry.options:
        options = {
            CONF_TIME_BETWEEN_UPDATE_COMMAND: DEFAULT_TIME_BETWEEN_UPDATE_COMMAND,
            CONF_RETRY_COUNT: DEFAULT_RETRY_COUNT,
            CONF_RETRY_TIMEOUT: DEFAULT_RETRY_TIMEOUT,
            CONF_SCAN_TIMEOUT: DEFAULT_SCAN_TIMEOUT,
        }

        hass.config_entries.async_update_entry(entry, options=options)

    if not hass.data[DOMAIN].get(DATA_COORDINATOR):

        switchbot.DEFAULT_RETRY_TIMEOUT = entry.options[CONF_RETRY_TIMEOUT]

        switchbot_api = switchbot

        coordinator = SwitchbotDataUpdateCoordinator(
            hass,
            update_interval=entry.options[CONF_TIME_BETWEEN_UPDATE_COMMAND],
            api=switchbot_api,
            retry_count=entry.options[CONF_RETRY_COUNT],
            scan_timeout=entry.options[CONF_SCAN_TIMEOUT],
        )

        await coordinator.async_config_entry_first_refresh()

        if not coordinator.last_update_success:
            raise ConfigEntryNotReady

        hass.data[DOMAIN][DATA_COORDINATOR] = coordinator

    undo_listener = entry.add_update_listener(_async_update_listener)

    hass.data[DOMAIN][entry.entry_id] = {DATA_UNDO_UPDATE_LISTENER: undo_listener}

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True


async def async_unload_entry(hass, entry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN][entry.entry_id][DATA_UNDO_UPDATE_LISTENER]()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_update_listener(hass, entry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
