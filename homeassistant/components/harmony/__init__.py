"""The Logitech Harmony Hub integration."""
import asyncio
import logging

from homeassistant.components.remote import ATTR_ACTIVITY, ATTR_DELAY_SECS
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.util import slugify

from .const import DOMAIN, PLATFORMS
from .remote import DEVICES, HarmonyRemote

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Logitech Harmony Hub component."""
    hass.data.setdefault(DOMAIN, {})

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Logitech Harmony Hub from a config entry."""

    conf = entry.data
    address = conf[CONF_HOST]
    name = conf.get(CONF_NAME)
    port = conf.get(CONF_PORT)
    activity = conf.get(ATTR_ACTIVITY)
    delay_secs = conf.get(ATTR_DELAY_SECS)

    _LOGGER.info(
        "Loading Harmony Platform: %s at %s:%s, startup activity: %s",
        name,
        address,
        port,
        activity,
    )

    harmony_conf_file = hass.config.path(f"harmony_{slugify(name)}.conf")
    try:
        device = HarmonyRemote(
            name, address, port, activity, harmony_conf_file, delay_secs
        )
    except (asyncio.TimeoutError, ValueError, AttributeError):
        raise ConfigEntryNotReady

    hass.data[DOMAIN][entry.entry_id] = device
    DEVICES.append(device)

    entry.add_update_listener(_update_listener)

    for component in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, component)
        )

    return True


async def _update_listener(hass, entry):
    """Handle options update."""

    device = hass.data[DOMAIN][entry.entry_id]

    device.delay_seconds = entry.options[ATTR_DELAY_SECS]
    device.default_activity = entry.options[ATTR_ACTIVITY]


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
    if unload_ok:
        DEVICES.remove(hass.data[DOMAIN][entry.entry_id])
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
