"""The Soundavo WS66i 6-Zone Amplifier integration."""
import logging

from pyws66i import get_ws66i

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from .const import CONF_SOURCES, DOMAIN, WS66I_OBJECT

PLATFORMS = ["media_player"]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Soundavo WS66i 6-Zone Amplifier from a config entry."""
    # Copy the config entry data to options for future use
    if not entry.options:
        options = {CONF_SOURCES: entry.data.get(CONF_SOURCES)}
        hass.config_entries.async_update_entry(entry, options=options)

    entry.async_on_unload(entry.add_update_listener(_update_listener))

    ws66i = get_ws66i(entry.data[CONF_IP_ADDRESS])
    try:
        await hass.async_add_executor_job(ws66i.open)
    except ConnectionError:
        # Amplifier is probably turned off
        _LOGGER.warning("Could not connect to WS66i Amp. Is it off?")
        return False

    def close(event):
        """Close the Telnet connection to the amplifier."""
        ws66i.close()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, close)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {WS66I_OBJECT: ws66i}

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN][entry.entry_id][WS66I_OBJECT].close()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
