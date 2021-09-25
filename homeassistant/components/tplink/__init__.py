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
from homeassistant.components.switch import ATTR_CURRENT_POWER_W, ATTR_TODAY_ENERGY_KWH
from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.const import ATTR_VOLTAGE, CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers import device_registry as dr, entity_registry as er
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_CURRENT_A,
    ATTR_TOTAL_ENERGY_KWH,
    CONF_DIMMER,
    CONF_DISCOVERY,
    CONF_EMETER_PARAMS,
    CONF_LEGACY_ENTRY_ID,
    CONF_LIGHT,
    CONF_STRIP,
    CONF_SWITCH,
    DISCOVERED_DEVICES,
    MAC_ADDRESS_LEN,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tplink"

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


async def async_migrate_legacy_entries(
    hass: HomeAssistant,
    legacy_entry: ConfigEntry,
    config_entries_by_mac: dict[str, ConfigEntry],
) -> None:
    """Migrate the legacy config entries to have an entry per device."""
    entity_registry = er.async_get(hass)
    tplink_reg_entities = er.async_entries_for_config_entry(
        entity_registry, legacy_entry.entry_id
    )

    for reg_entity in tplink_reg_entities:
        # Only migrate entities with a mac address only
        if len(reg_entity.unique_id) != MAC_ADDRESS_LEN:
            continue
        mac = dr.format_mac(reg_entity.unique_id)
        if mac in config_entries_by_mac:
            continue

        domain = (split_entity_id(reg_entity.entity_id))[0]
        if domain not in ("switch", "light"):
            continue
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "migration"},
                data={
                    CONF_LEGACY_ENTRY_ID: reg_entity.entry_id,
                    CONF_MAC: dr.format_mac(reg_entity.unique_id),
                    CONF_NAME: reg_entity.name,
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
        if entry.unique_id is None:
            legacy_entry = entry
        else:
            config_entries_by_mac[entry.unique_id] = entry

    discovered_devices = {
        dr.format_mac(device.mac): device
        for device in (await Discover.discover()).values()
    }
    hass.data[DOMAIN][DISCOVERED_DEVICES] = discovered_devices

    if legacy_entry:
        await async_migrate_legacy_entries(hass, legacy_entry)

    if conf is not None:
        for device_type in (CONF_LIGHT, CONF_SWITCH, CONF_STRIP, CONF_DIMMER):
            if device_type not in conf:
                continue
            for device in conf[device_type]:
                hass.async_create_task(
                    hass.config_entries.flow.async_init(
                        DOMAIN,
                        context={"source": config_entries.SOURCE_IMPORT},
                        data={
                            CONF_HOST: device[CONF_HOST],
                        },
                    )
                )

    for formatted_mac, device in discovered_devices:
        formatted_mac = dr.format_mac(device.mac)
        if formatted_mac in config_entries_by_mac:
            continue
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

    return True


async def async_migrate_entities(
    hass: HomeAssistant, legacy_entry_id: str, new_entry: ConfigEntry
) -> None:
    """Move entities to the new config entry."""
    entity_registry = er.async_get(hass)
    tplink_reg_entities = er.async_entries_for_config_entry(
        entity_registry, legacy_entry_id
    )

    for reg_entity in tplink_reg_entities:
        # Only migrate entities with a mac address only
        if len(reg_entity.unique_id) < MAC_ADDRESS_LEN:
            continue
        mac = reg_entity.unique_id[:MAC_ADDRESS_LEN]
        formatted_mac = dr.format_mac(mac)
        if formatted_mac != new_entry.unique_id:
            continue
        er._async_update_entity(
            reg_entity.entity_id, config_entry_id=new_entry.entry_id
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up TPLink from a config entry."""
    if not entry.unique_id:
        return False

    if legacy_entry_id := entry.data.get(CONF_LEGACY_ENTRY_ID):
        await async_migrate_entities(hass, legacy_entry_id, entry.entry_id)

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
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass_data: dict[str, Any] = hass.data[DOMAIN]
    if unload_ok:
        hass_data.clear()

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
            name=device.alias,
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
