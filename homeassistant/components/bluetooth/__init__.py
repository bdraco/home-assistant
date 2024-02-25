"""The bluetooth integration."""
from __future__ import annotations

import datetime
import logging
import platform
import time
from typing import TYPE_CHECKING

from bleak_retry_connector import BleakSlotManager
from bluetooth_adapters import (
    ADAPTER_ADDRESS,
    ADAPTER_CONNECTION_SLOTS,
    ADAPTER_HW_VERSION,
    ADAPTER_MANUFACTURER,
    ADAPTER_SW_VERSION,
    DEFAULT_ADDRESS,
    DEFAULT_CONNECTION_SLOTS,
    AdapterDetails,
    BluetoothAdapters,
    adapter_human_name,
    adapter_model,
    adapter_unique_name,
    get_adapters,
)
from bluetooth_data_tools import monotonic_time_coarse as MONOTONIC_TIME
from habluetooth import (
    BaseHaRemoteScanner,
    BaseHaScanner,
    BluetoothScannerDevice,
    BluetoothScanningMode,
    HaBluetoothConnector,
    HaScanner,
    ScannerStartError,
    set_manager,
)
from home_assistant_bluetooth import BluetoothServiceInfo, BluetoothServiceInfoBleak

from homeassistant.components import usb
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HassJob, HomeAssistant, callback as hass_callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    discovery_flow,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.issue_registry import async_delete_issue
from homeassistant.loader import async_get_bluetooth

from . import models, passive_update_processor
from .api import (
    _get_manager,
    async_address_present,
    async_ble_device_from_address,
    async_discovered_service_info,
    async_get_advertisement_callback,
    async_get_fallback_availability_interval,
    async_get_learned_advertising_interval,
    async_get_scanner,
    async_last_service_info,
    async_process_advertisements,
    async_rediscover_address,
    async_register_callback,
    async_register_scanner,
    async_scanner_by_source,
    async_scanner_count,
    async_scanner_devices_by_address,
    async_set_fallback_availability_interval,
    async_track_unavailable,
)
from .const import (
    BLUETOOTH_DISCOVERY_COOLDOWN_SECONDS,
    CONF_ADAPTER,
    CONF_DETAILS,
    CONF_PASSIVE,
    DATA_MANAGER,
    DOMAIN,
    FALLBACK_MAXIMUM_STALE_ADVERTISEMENT_SECONDS,
    LINUX_FIRMWARE_LOAD_FALLBACK_SECONDS,
    SOURCE_LOCAL,
)
from .manager import HomeAssistantBluetoothManager
from .match import BluetoothCallbackMatcher, IntegrationMatcher
from .models import BluetoothCallback, BluetoothChange
from .storage import BluetoothStorage

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

__all__ = [
    "async_address_present",
    "async_ble_device_from_address",
    "async_discovered_service_info",
    "async_get_fallback_availability_interval",
    "async_get_learned_advertising_interval",
    "async_get_scanner",
    "async_last_service_info",
    "async_process_advertisements",
    "async_rediscover_address",
    "async_register_callback",
    "async_register_scanner",
    "async_set_fallback_availability_interval",
    "async_track_unavailable",
    "async_scanner_by_source",
    "async_scanner_count",
    "async_scanner_devices_by_address",
    "async_get_advertisement_callback",
    "BaseHaScanner",
    "HomeAssistantRemoteScanner",
    "BluetoothCallbackMatcher",
    "BluetoothChange",
    "BluetoothServiceInfo",
    "BluetoothServiceInfoBleak",
    "BluetoothScanningMode",
    "BluetoothCallback",
    "BluetoothScannerDevice",
    "HaBluetoothConnector",
    "BaseHaRemoteScanner",
    "SOURCE_LOCAL",
    "FALLBACK_MAXIMUM_STALE_ADVERTISEMENT_SECONDS",
    "MONOTONIC_TIME",
]

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def _async_get_adapter_from_address(
    hass: HomeAssistant, address: str
) -> str | None:
    """Get an adapter by the address."""
    return await _get_manager(hass).async_get_adapter_from_address(address)


async def _async_start_adapter_discovery(
    hass: HomeAssistant,
    manager: HomeAssistantBluetoothManager,
    bluetooth_adapters: BluetoothAdapters,
) -> None:
    """Start adapter discovery."""
    adapters = await manager.async_get_bluetooth_adapters()
    async_migrate_entries(hass, adapters, bluetooth_adapters.default_adapter)
    await async_discover_adapters(hass, adapters)

    async def _async_rediscover_adapters() -> None:
        """Rediscover adapters when a new one may be available."""
        discovered_adapters = await manager.async_get_bluetooth_adapters(cached=False)
        _LOGGER.debug("Rediscovered adapters: %s", discovered_adapters)
        await async_discover_adapters(hass, discovered_adapters)

    discovery_debouncer = Debouncer(
        hass,
        _LOGGER,
        cooldown=BLUETOOTH_DISCOVERY_COOLDOWN_SECONDS,
        immediate=False,
        function=_async_rediscover_adapters,
    )

    @hass_callback
    def _async_shutdown_debouncer(_: Event) -> None:
        """Shutdown debouncer."""
        discovery_debouncer.async_shutdown()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_shutdown_debouncer)

    async def _async_call_debouncer(now: datetime.datetime) -> None:
        """Call the debouncer at a later time."""
        await discovery_debouncer.async_call()

    call_debouncer_job = HassJob(_async_call_debouncer, cancel_on_shutdown=True)

    def _async_trigger_discovery() -> None:
        # There are so many bluetooth adapter models that
        # we check the bus whenever a usb device is plugged in
        # to see if it is a bluetooth adapter since we can't
        # tell if the device is a bluetooth adapter or if its
        # actually supported unless we ask DBus if its now
        # present.
        _LOGGER.debug("Triggering bluetooth usb discovery")
        hass.async_create_task(discovery_debouncer.async_call())
        # Because it can take 120s for the firmware loader
        # fallback to timeout we need to wait that plus
        # the debounce time to ensure we do not miss the
        # adapter becoming available to DBus since otherwise
        # we will never see the new adapter until
        # Home Assistant is restarted
        async_call_later(
            hass,
            BLUETOOTH_DISCOVERY_COOLDOWN_SECONDS + LINUX_FIRMWARE_LOAD_FALLBACK_SECONDS,
            call_debouncer_job,
        )

    cancel = usb.async_register_scan_request_callback(hass, _async_trigger_discovery)
    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, hass_callback(lambda event: cancel())
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the bluetooth integration."""
    bluetooth_start = time.monotonic()
    bluetooth_adapters = get_adapters()
    bluetooth_storage = BluetoothStorage(hass)
    slot_manager = BleakSlotManager()

    integration_matcher = IntegrationMatcher(await async_get_bluetooth(hass))
    integration_matcher_finished = time.monotonic()
    _LOGGER.warning(
        "Integration matcher finished in %s seconds",
        integration_matcher_finished - bluetooth_start,
    )

    slot_manager_setup_task = hass.async_create_task(
        slot_manager.async_setup(), "slot_manager setup"
    )
    slot_manager_task_time = time.monotonic()
    _LOGGER.warning(
        "Slot manager task started in %s seconds",
        slot_manager_task_time - integration_matcher_finished,
    )
    processor_setup_task = hass.async_create_task(
        passive_update_processor.async_setup(hass), "passive_update_processor setup"
    )
    passive_processor_task_time = time.monotonic()
    _LOGGER.warning(
        "Passive processor task started in %s seconds",
        passive_processor_task_time - slot_manager_task_time,
    )
    storage_setup_task = hass.async_create_task(
        bluetooth_storage.async_setup(), "bluetooth storage setup"
    )
    storage_task_time = time.monotonic()
    _LOGGER.warning(
        "Storage task started in %s seconds",
        storage_task_time - passive_processor_task_time,
    )
    integration_matcher.async_setup()
    integration_matcher_time = time.monotonic()
    _LOGGER.warning(
        "Integration matcher setup finished in %s seconds",
        integration_matcher_time - storage_task_time,
    )
    manager = HomeAssistantBluetoothManager(
        hass, integration_matcher, bluetooth_adapters, bluetooth_storage, slot_manager
    )
    manager_create_time = time.monotonic()
    _LOGGER.warning(
        "Manager created in %s seconds",
        manager_create_time - integration_matcher_time,
    )

    set_manager(manager)

    await storage_setup_task
    storage_finished = time.monotonic()
    _LOGGER.warning(
        "Storage setup finished in %s seconds",
        storage_finished - manager_create_time,
    )
    await manager.async_setup()
    manager_finished = time.monotonic()
    _LOGGER.warning(
        "Manager setup finished in %s seconds",
        manager_finished - storage_finished,
    )

    hass.data[DATA_MANAGER] = models.MANAGER = manager

    hass.async_create_background_task(
        _async_start_adapter_discovery(hass, manager, bluetooth_adapters),
        "start_adapter_discovery",
    )
    await slot_manager_setup_task
    async_delete_issue(hass, DOMAIN, "haos_outdated")
    await processor_setup_task
    return True


@hass_callback
def async_migrate_entries(
    hass: HomeAssistant, adapters: dict[str, AdapterDetails], default_adapter: str
) -> None:
    """Migrate config entries to support multiple."""
    current_entries = hass.config_entries.async_entries(DOMAIN)

    for entry in current_entries:
        if entry.unique_id:
            continue

        address = DEFAULT_ADDRESS
        adapter = entry.options.get(CONF_ADAPTER, default_adapter)
        if adapter in adapters:
            address = adapters[adapter][ADAPTER_ADDRESS]
        hass.config_entries.async_update_entry(
            entry, title=adapter_unique_name(adapter, address), unique_id=address
        )


async def async_discover_adapters(
    hass: HomeAssistant,
    adapters: dict[str, AdapterDetails],
) -> None:
    """Discover adapters and start flows."""
    if platform.system() == "Windows":
        # We currently do not have a good way to detect if a bluetooth device is
        # available on Windows. We will just assume that it is not unless they
        # actively add it.
        return

    for adapter, details in adapters.items():
        discovery_flow.async_create_flow(
            hass,
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={CONF_ADAPTER: adapter, CONF_DETAILS: details},
        )


async def async_update_device(
    hass: HomeAssistant, entry: ConfigEntry, adapter: str, details: AdapterDetails
) -> None:
    """Update device registry entry.

    The physical adapter can change from hci0/hci1 on reboot
    or if the user moves around the usb sticks so we need to
    update the device with the new location so they can
    figure out where the adapter is.
    """
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        name=adapter_human_name(adapter, details[ADAPTER_ADDRESS]),
        connections={(dr.CONNECTION_BLUETOOTH, details[ADAPTER_ADDRESS])},
        manufacturer=details[ADAPTER_MANUFACTURER],
        model=adapter_model(details),
        sw_version=details.get(ADAPTER_SW_VERSION),
        hw_version=details.get(ADAPTER_HW_VERSION),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry for a bluetooth scanner."""
    address = entry.unique_id
    assert address is not None
    adapter = await _async_get_adapter_from_address(hass, address)
    if adapter is None:
        raise ConfigEntryNotReady(
            f"Bluetooth adapter {adapter} with address {address} not found"
        )

    passive = entry.options.get(CONF_PASSIVE)
    mode = BluetoothScanningMode.PASSIVE if passive else BluetoothScanningMode.ACTIVE
    manager: HomeAssistantBluetoothManager = hass.data[DATA_MANAGER]
    scanner = HaScanner(mode, adapter, address)
    try:
        scanner.async_setup()
    except RuntimeError as err:
        raise ConfigEntryNotReady(
            f"{adapter_human_name(adapter, address)}: {err}"
        ) from err
    try:
        await scanner.async_start()
    except ScannerStartError as err:
        raise ConfigEntryNotReady from err
    adapters = await manager.async_get_bluetooth_adapters()
    details = adapters[adapter]
    slots: int = details.get(ADAPTER_CONNECTION_SLOTS) or DEFAULT_CONNECTION_SLOTS
    entry.async_on_unload(async_register_scanner(hass, scanner, connection_slots=slots))
    await async_update_device(hass, entry, adapter, details)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = scanner
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    scanner: HaScanner = hass.data[DOMAIN].pop(entry.entry_id)
    await scanner.async_stop()
    return True
