"""The Nmap Tracker integration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
import logging

from getmac import get_mac_address
from mac_vendor_lookup import MacLookup
from nmap import PortScanner, PortScannerError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EXCLUDE, CONF_HOSTS, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import (
    CONF_HOME_INTERVAL,
    CONF_OPTIONS,
    DOMAIN,
    NMAP_TRACKED_DEVICES,
    PLATFORMS,
    TRACKER_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nmap Tracker from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    devices = domain_data.setdefault(NMAP_TRACKED_DEVICES, NmapTrackedDevices())
    scanner = domain_data[entry.entry_id] = NmapDeviceScanner(hass, entry, devices)
    scanner.async_setup()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


@dataclass
class NmapDevice:
    """Class for keeping track of an nmap tracked device."""

    mac_address: str
    hostname: str
    ipv4: str
    manufacturer: str
    last_update: datetime.datetime


class NmapTrackedDevices:
    """Storage class for platform global data."""

    def __init__(self) -> None:
        """Initialize the data."""
        self.tracked: dict = {}


class NmapDeviceScanner:
    """This class scans for devices using nmap."""

    def __init__(self, hass, entry, devices):
        """Initialize the scanner."""
        self._hass = hass
        self._entry = entry
        self._scan_lock = None
        self._stopping = False
        self._entry_id = entry.entry_id
        self.devices = devices
        self.mac_vendor_lookup = None

        config = entry.options
        self.last_results = []
        self.hosts = cv.ensure_list(config[CONF_HOSTS])
        self.exclude = cv.ensure_list(config[CONF_EXCLUDE])
        minutes = cv.positive_int(config[CONF_HOME_INTERVAL])
        self._options = config[CONF_OPTIONS]
        self.home_interval = timedelta(minutes=minutes)

    @callback
    def async_setup(self):
        """Set up the tracker."""
        self._scan_lock = asyncio.Lock()
        self.scanner = PortScanner()
        self._hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, self._start_scanner
        )

    @lru_cache(max_size=None)
    def get_manufacturer(self, mac_address):
        """Lookup the manufacturer."""
        return self.mac_vendor_lookup.lookup(mac_address)

    @callback
    def _async_stop(self):
        """Stop the scanner."""
        self._stopping = True

    def _start_scanner(self, *_):
        """Start the scanner."""
        self._entry.async_on_unload(self._async_stop)
        self._entry.async_on_unload(
            async_track_time_interval(
                self._hass,
                self.async_scan_devices,
                timedelta(seconds=TRACKER_SCAN_INTERVAL),
            )
        )
        self._hass.async_create_task(self.async_scan_devices())

    @property
    def signal_device_new(self) -> str:
        """Signal specific per nmap tracker entry to signal new device."""
        return f"{DOMAIN}-device-new-{self._entry_id}"

    def signal_device_update(self, ipv4) -> str:
        """Signal specific per nmap tracker entry to signal updates in device."""
        return f"{DOMAIN}-device-update-{ipv4}"

    def _build_options(self):
        """Build the command line and strip out last results that do not need to be updated."""
        options = self._options
        if self.home_interval:
            boundary = dt_util.now() - self.home_interval
            last_results = [
                device for device in self.last_results if device.last_update > boundary
            ]
            if last_results:
                exclude_hosts = self.exclude + [device.ipv4 for device in last_results]
            else:
                exclude_hosts = self.exclude
        else:
            last_results = []
            exclude_hosts = self.exclude
        if exclude_hosts:
            options += f" --exclude {','.join(exclude_hosts)}"
        self.last_results = last_results
        return options

    async def async_scan_devices(self, *_):
        """Scan devices and dispatch."""
        if self._scan_lock.locked():
            _LOGGER.debug(
                "Nmap scanning is taking longer than the scheduled interval: %s",
                TRACKER_SCAN_INTERVAL,
            )
            return

        async with self._scan_lock:
            try:
                dispatches = await self._hass.async_add_executor_job(
                    self._run_nmap_scan
                )
            except PortScannerError as ex:
                _LOGGER.error("Nmap scanning failed: %s", ex)
            else:
                for signal, ipv4 in dispatches:
                    async_dispatcher_send(self._hass, signal, ipv4)

    def _run_nmap_scan(self):
        """Scan the network for devices.

        Returns boolean if scanning successful.
        """
        options = self._build_options()
        if not self.mac_vendor_lookup:
            self.mac_vendor_lookup = MacLookup()
        dispatches = []

        _LOGGER.debug("Scanning %s with args: %s", self.hosts, options)

        result = self.scanner.scan(
            hosts=" ".join(self.hosts),
            arguments=options,
        )

        if self._stopping:
            return dispatches
        for ipv4, info in result["scan"].items():
            if info["status"]["state"] != "up":
                if ipv4 in self.devices.tracked:
                    dispatches.append((self.signal_device_update(ipv4), False))
                self.offline_devices.add(ipv4)
                continue
            name = info["hostnames"][0]["name"] if info["hostnames"] else ipv4
            # Mac address only returned if nmap ran as root
            mac = info["addresses"].get("mac") or get_mac_address(ip=ipv4)
            if mac is None:
                _LOGGER.info("No MAC address found for %s", ipv4)
                continue

            manufacturer = self.get_manufacturer(mac)
            device = NmapDevice(
                format_mac(mac), name, ipv4, manufacturer, dt_util.now()
            )
            dispatches.append((self.signal_device_update(ipv4), True))
            if self.devices.tracked.setdefault(ipv4, device) is device:
                dispatches.append((self.signal_device_new, ipv4))
            else:
                self.devices.tracked[ipv4] = device
            self.last_results.append(device)
        return dispatches
