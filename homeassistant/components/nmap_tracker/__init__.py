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
from homeassistant.core import CoreState, HomeAssistant, callback
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

# Some version of nmap will fail with 'Assertion failed: htn.toclock_running == true (Target.cc: stopTimeOutClock: 503)\n'
NMAP_TRANSIENT_FAILURE = "Assertion failed: htn.toclock_running == true"
MAX_SCAN_ATTEMPTS = 10
OFFLINE_SCANS_TO_MARK_UNAVAILABLE = 3


@dataclass
class NmapDevice:
    """Class for keeping track of an nmap tracked device."""

    mac_address: str
    hostname: str
    ipv4: str
    manufacturer: str
    reason: str
    last_update: datetime.datetime
    offline_scans: int


class NmapTrackedDevices:
    """Storage class for all nmap trackers."""

    def __init__(self) -> None:
        """Initialize the data."""
        self.tracked: dict = {}
        self.ipv4_last_mac: dict = {}
        self.config_entry_owner: dict = {}


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
        _async_untrack_devices(hass, entry)
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


@callback
def _async_untrack_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove tracking for devices owned by this config entry."""
    devices = hass.data[DOMAIN][NMAP_TRACKED_DEVICES]
    remove_mac_addresses = [
        mac_address
        for mac_address, entry_id in devices.config_entry_owner.items()
        if entry_id == entry.entry_id
    ]
    for mac_address in remove_mac_addresses:
        if device := devices.tracked.pop(mac_address, None):
            devices.ipv4_last_mac.pop(device.ipv4, None)
        del devices.config_entry_owner[mac_address]


def signal_device_update(mac_address) -> str:
    """Signal specific per nmap tracker entry to signal updates in device."""
    return f"{DOMAIN}-device-update-{mac_address}"


class NmapDeviceScanner:
    """This class scans for devices using nmap."""

    def __init__(self, hass, entry, devices):
        """Initialize the scanner."""
        self.devices = devices
        self.home_interval = None

        self._hass = hass
        self._entry = entry

        self._scan_lock = None
        self._stopping = False
        self._scanner = None

        self._entry_id = entry.entry_id
        self._hosts = None
        self._options = None
        self._exclude = None

        self._last_results = []
        self._mac_vendor_lookup = None

    @callback
    def async_setup(self):
        """Set up the tracker."""
        config = self._entry.options
        self._hosts = cv.ensure_list_csv(config[CONF_HOSTS])
        self._exclude = cv.ensure_list_csv(config[CONF_EXCLUDE])
        self._options = config[CONF_OPTIONS]
        self.home_interval = timedelta(
            minutes=cv.positive_int(config[CONF_HOME_INTERVAL])
        )
        self._scan_lock = asyncio.Lock()
        if self._hass.state == CoreState.running:
            self._async_start_scanner()
            return

        self._hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, self._async_start_scanner
        )

    @property
    def signal_device_new(self) -> str:
        """Signal specific per nmap tracker entry to signal new device."""
        return f"{DOMAIN}-device-new-{self._entry_id}"

    @lru_cache(maxsize=4096)
    def _get_vendor(self, oui):
        """Lookup the vendor."""
        try:
            return self._mac_vendor_lookup.lookup(oui)
        except KeyError:
            return None

    @callback
    def _async_stop(self):
        """Stop the scanner."""
        self._stopping = True

    @callback
    def _async_start_scanner(self, *_):
        """Start the scanner."""
        self._entry.async_on_unload(self._async_stop)
        self._entry.async_on_unload(
            async_track_time_interval(
                self._hass,
                self._async_scan_devices,
                timedelta(seconds=TRACKER_SCAN_INTERVAL),
            )
        )
        self._hass.async_create_task(self._async_scan_devices())

    def _build_options(self):
        """Build the command line and strip out last results that do not need to be updated."""
        options = self._options
        if self.home_interval:
            boundary = dt_util.now() - self.home_interval
            last_results = [
                device for device in self._last_results if device.last_update > boundary
            ]
            if last_results:
                exclude_hosts = self._exclude + [device.ipv4 for device in last_results]
            else:
                exclude_hosts = self._exclude
        else:
            last_results = []
            exclude_hosts = self._exclude
        if exclude_hosts:
            options += f" --exclude {','.join(exclude_hosts)}"
        # Report reason
        if "--reason" not in options:
            options += " --reason"
        # Report down hosts
        if "-v" not in options:
            options += " -v"
        self._last_results = last_results
        return options

    async def _async_scan_devices(self, *_):
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
                    self._start_nmap_scan
                )
            except PortScannerError as ex:
                _LOGGER.error("Nmap scanning failed: %s", ex)
            else:
                for signal, ipv4 in dispatches:
                    async_dispatcher_send(self._hass, signal, ipv4)

    def _run_nmap_scan(self):
        """Run nmap and return the result."""
        options = self._build_options()
        if not self._mac_vendor_lookup:
            self._mac_vendor_lookup = MacLookup()
        if not self._scanner:
            self._scanner = PortScanner()
        _LOGGER.debug("Scanning %s with args: %s", self._hosts, options)
        for attempt in range(MAX_SCAN_ATTEMPTS):
            try:
                result = self._scanner.scan(
                    hosts=" ".join(self._hosts),
                    arguments=options,
                    timeout=TRACKER_SCAN_INTERVAL * 10,
                )
                break
            except PortScannerError as ex:
                if attempt < (MAX_SCAN_ATTEMPTS - 1) and NMAP_TRANSIENT_FAILURE in str(
                    ex
                ):
                    _LOGGER.debug("Nmap saw transient error %s", NMAP_TRANSIENT_FAILURE)
                    continue
                raise
        _LOGGER.debug(
            "Finished scanning %s with args: %s",
            self._hosts,
            options,
        )
        return result

    def _increment_device_offline(self, ipv4, reason, dispatches):
        """Mark an IP offline."""
        if ipv4 not in self.devices.ipv4_last_mac:
            return
        formatted_mac = self.devices.ipv4_last_mac[ipv4]
        device = self.devices.tracked[formatted_mac]
        device.offline_scans += 1
        if device.offline_scans < OFFLINE_SCANS_TO_MARK_UNAVAILABLE:
            return
        device.reason = reason
        dispatches.append((signal_device_update(formatted_mac), False))
        del self.devices.ipv4_last_mac[ipv4]

    def _start_nmap_scan(self):
        """Scan the network for devices.

        Returns dispatches to callback if scanning successful.
        """
        result = self._run_nmap_scan()
        if self._stopping:
            return []

        dispatches = []
        devices = self.devices
        entry_id = self._entry_id
        now = dt_util.now()
        for ipv4, info in result["scan"].items():
            status = info["status"]
            reason = status["reason"]
            if status["state"] != "up":
                self._increment_device_offline(ipv4, reason, dispatches)
                continue
            # Mac address only returned if nmap ran as root
            mac = info["addresses"].get("mac") or get_mac_address(ip=ipv4)
            if mac is None:
                self._increment_device_offline(ipv4, "No MAC address found", dispatches)
                _LOGGER.info("No MAC address found for %s", ipv4)
                continue

            name = info["hostnames"][0]["name"] if info["hostnames"] else ipv4

            formatted_mac = format_mac(mac)
            if (
                devices.config_entry_owner.setdefault(formatted_mac, entry_id)
                != entry_id
            ):
                continue

            vendor = info.get("vendor", {}).get(mac) or self._get_vendor(
                self._mac_vendor_lookup.sanitise(mac)[:6]
            )
            device = NmapDevice(formatted_mac, name, ipv4, vendor, reason, now, 0)
            if formatted_mac not in devices.tracked:
                dispatches.append((self.signal_device_new, formatted_mac))
            dispatches.append((signal_device_update(formatted_mac), True))

            devices.tracked[formatted_mac] = device
            devices.ipv4_last_mac[ipv4] = formatted_mac
            self._last_results.append(device)

        return dispatches
