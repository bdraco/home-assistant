"""Component to embed TP-Link smart home devices."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from kasa import SmartDevice, SmartDeviceException
from kasa.discover import Discover
from kasa.protocol import TPLinkSmartHomeProtocol
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.const import ATTR_VOLTAGE, CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_CURRENT_A,
    ATTR_CURRENT_POWER_W,
    ATTR_TODAY_ENERGY_KWH,
    ATTR_TOTAL_ENERGY_KWH,
    CONF_DIMMER,
    CONF_DISCOVERY,
    CONF_EMETER_PARAMS,
    CONF_LEGACY_ENTRY_ID,
    CONF_LIGHT,
    CONF_STRIP,
    CONF_SWITCH,
    DISCOVERED_DEVICES,
    DOMAIN,
    PLATFORMS,
)
from .migration import (
    async_migrate_entities_devices,
    async_migrate_legacy_entries,
    async_migrate_yaml_entries,
)

_LOGGER = logging.getLogger(__name__)

TPLINK_HOST_SCHEMA = vol.Schema({vol.Required(CONF_HOST): cv.string})

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_LIGHT, default=[]): vol.All(
                    cv.ensure_list, [TPLINK_HOST_SCHEMA]
                ),
                vol.Optional(CONF_SWITCH, default=[]): vol.All(
                    cv.ensure_list, [TPLINK_HOST_SCHEMA]
                ),
                vol.Optional(CONF_STRIP, default=[]): vol.All(
                    cv.ensure_list, [TPLINK_HOST_SCHEMA]
                ),
                vol.Optional(CONF_DIMMER, default=[]): vol.All(
                    cv.ensure_list, [TPLINK_HOST_SCHEMA]
                ),
                vol.Optional(CONF_DISCOVERY, default=True): cv.boolean,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


@callback
def async_trigger_discovery(
    hass: HomeAssistant,
    discovered_devices: dict[str, SmartDevice],
) -> None:
    """Trigger config flows for discovered devices."""
    for formatted_mac, device in discovered_devices.items():
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_DISCOVERY},
                data={
                    CONF_NAME: device.alias,
                    CONF_HOST: device.host,
                    CONF_MAC: formatted_mac,
                },
            )
        )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the TP-Link component."""
    conf = config.get(DOMAIN)
    hass.data[DOMAIN] = {}

    legacy_entry = None
    config_entries_by_mac = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.unique_id is None or entry.unique_id == DOMAIN:
            legacy_entry = entry
        else:
            config_entries_by_mac[entry.unique_id] = entry

    discovered_devices = {
        dr.format_mac(device.mac): device
        for device in (await Discover.discover()).values()
    }
    hass.data[DOMAIN][DISCOVERED_DEVICES] = discovered_devices

    if legacy_entry:
        async_migrate_legacy_entries(hass, config_entries_by_mac, legacy_entry)

    if conf is not None:
        async_migrate_yaml_entries(hass, conf)

    if discovered_devices:
        async_trigger_discovery(hass, discovered_devices)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up TPLink from a config entry."""
    if not entry.unique_id or entry.unique_id == DOMAIN:
        return True

    if legacy_entry_id := entry.data.get(CONF_LEGACY_ENTRY_ID):
        await async_migrate_entities_devices(hass, legacy_entry_id, entry)

    protocol = TPLinkSmartHomeProtocol(entry.data[CONF_HOST])
    try:
        info = await protocol.query(Discover.DISCOVERY_QUERY)
    except SmartDeviceException as ex:
        raise ConfigEntryNotReady from ex

    device_class = Discover._get_device_class(info)  # pylint: disable=protected-access
    device = device_class(entry.data[CONF_HOST])
    coordinator = TPLinkDataUpdateCoordinator(hass, device)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass_data: dict[str, Any] = hass.data[DOMAIN]
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        if entry.entry_id in hass_data:
            hass_data.pop(entry.entry_id)
    return unload_ok


class TPLinkDataUpdateCoordinator(DataUpdateCoordinator):
    """DataUpdateCoordinator to gather data for specific SmartPlug."""

    def __init__(
        self,
        hass: HomeAssistant,
        device: SmartDevice,
    ) -> None:
        """Initialize DataUpdateCoordinator to gather data for specific SmartPlug."""
        self.device = device
        self.update_children = True
        update_interval = timedelta(seconds=10)
        super().__init__(
            hass,
            _LOGGER,
            name=device.host,
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> dict:
        """Fetch all device and sensor data from api."""
        try:
            await self.device.update(update_children=self.update_children)
        except SmartDeviceException as ex:
            raise UpdateFailed(ex) from ex
        else:
            self.update_children = True

        self.name = self.device.alias

        # Check if the device has emeter
        if not self.device.has_emeter:
            return {}

        if (emeter_today := self.device.emeter_today) is not None:
            consumption_today = emeter_today
        else:
            # today's consumption not available, when device was off all the day
            # bulb's do not report this information, so filter it out
            consumption_today = None if self.device.is_bulb else 0.0

        emeter_readings = self.device.emeter_realtime
        return {
            CONF_EMETER_PARAMS: {
                ATTR_CURRENT_POWER_W: emeter_readings.power,
                ATTR_TOTAL_ENERGY_KWH: emeter_readings.total,
                ATTR_VOLTAGE: emeter_readings.voltage,
                ATTR_CURRENT_A: emeter_readings.current,
                ATTR_TODAY_ENERGY_KWH: consumption_today,
            }
        }
