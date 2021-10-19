"""The lookin integration."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .aiolookin import (
    DeviceNotFound,
    LookInHttpProtocol,
    LookinUDPSubscriptions,
    start_lookin_udp,
)
from .const import DOMAIN, LOGGER, PLATFORMS
from .models import LookinData


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up lookin from a config entry."""

    host = entry.data[CONF_HOST]
    lookin_protocol = LookInHttpProtocol(
        host=host, session=async_get_clientsession(hass)
    )

    try:
        lookin_device = await lookin_protocol.get_info()
        devices = await lookin_protocol.get_devices()
    except DeviceNotFound as ex:
        raise ConfigEntryNotReady from ex

    meteo_coordinator: DataUpdateCoordinator = DataUpdateCoordinator(
        hass,
        LOGGER,
        name=entry.title,
        update_method=lookin_protocol.get_meteo_sensor,
        update_interval=timedelta(seconds=15),
    )
    await meteo_coordinator.async_config_entry_first_refresh()

    lookin_udp_subs = LookinUDPSubscriptions()
    entry.async_on_unload(await start_lookin_udp(lookin_udp_subs))

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = LookinData(
        lookin_udp_subs=lookin_udp_subs,
        lookin_device=lookin_device,
        meteo_coordinator=meteo_coordinator,
        devices=devices,
        lookin_protocol=lookin_protocol,
    )

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True
