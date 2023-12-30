"""Support for monitoring the local system."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache, lru_cache
import logging
import os
import socket
import sys
from typing import Any, Literal

import psutil
from psutil._common import sdiskusage, sswap
from psutil._pslinux import svmem
import voluptuous as vol

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_RESOURCES,
    CONF_TYPE,
    EVENT_HOMEASSISTANT_STOP,
    PERCENTAGE,
    STATE_OFF,
    STATE_ON,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity_component import DEFAULT_SCAN_INTERVAL
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import slugify
import homeassistant.util.dt as dt_util

from .const import CONF_PROCESS, DOMAIN, NETWORK_TYPES
from .util import get_all_disk_mounts, get_all_network_interfaces

_LOGGER = logging.getLogger(__name__)

CONF_ARG = "arg"


SENSOR_TYPE_NAME = 0
SENSOR_TYPE_UOM = 1
SENSOR_TYPE_ICON = 2
SENSOR_TYPE_DEVICE_CLASS = 3
SENSOR_TYPE_MANDATORY_ARG = 4

SIGNAL_SYSTEMMONITOR_UPDATE = "systemmonitor_update"


@lru_cache
def get_cpu_icon() -> Literal["mdi:cpu-64-bit", "mdi:cpu-32-bit"]:
    """Return cpu icon."""
    if sys.maxsize > 2**32:
        return "mdi:cpu-64-bit"
    return "mdi:cpu-32-bit"


@dataclass(frozen=True)
class SysMonitorSensorEntityDescription(SensorEntityDescription):
    """Description for System Monitor sensor entities."""

    mandatory_arg: bool = False
    value_disk: Callable[[sdiskusage], float] | None = None
    value_swap: Callable[[sswap], float] | None = None
    value_memory: Callable[[svmem], float] | None = None
    value_net_io: Callable[[int], float] | None = None
    value_net_throughput: Callable[[float], float] | None = None
    value_net_addr: Callable[[str], str] | None = None
    value_load: Callable[[tuple[float, float, float]], float] | None = None
    value_processor: Callable[[float], float] | None = None
    value_boot_time: Callable[[datetime], datetime] | None = None
    value_process: Callable[[bool], str] | None = None
    value_cpu_temp: Callable[[float], float] | None = None


SENSOR_TYPES: dict[str, SysMonitorSensorEntityDescription] = {
    "disk_free": SysMonitorSensorEntityDescription(
        key="disk_free",
        name="Disk free",
        native_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
        value_disk=lambda data: round(data.free / 1024**3, 1),
    ),
    "disk_use": SysMonitorSensorEntityDescription(
        key="disk_use",
        name="Disk use",
        native_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
        value_disk=lambda data: round(data.used / 1024**3, 1),
    ),
    "disk_use_percent": SysMonitorSensorEntityDescription(
        key="disk_use_percent",
        name="Disk use (percent)",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
        value_disk=lambda data: data.percent,
    ),
    "ipv4_address": SysMonitorSensorEntityDescription(
        key="ipv4_address",
        name="IPv4 address",
        icon="mdi:ip-network",
        mandatory_arg=True,
        value_net_addr=lambda data: data,
    ),
    "ipv6_address": SysMonitorSensorEntityDescription(
        key="ipv6_address",
        name="IPv6 address",
        icon="mdi:ip-network",
        mandatory_arg=True,
        value_net_addr=lambda data: data,
    ),
    "last_boot": SysMonitorSensorEntityDescription(
        key="last_boot",
        name="Last boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_boot_time=lambda data: data,
    ),
    "load_15m": SysMonitorSensorEntityDescription(
        key="load_15m",
        name="Load (15m)",
        icon=get_cpu_icon(),
        state_class=SensorStateClass.MEASUREMENT,
        value_load=lambda data: round(data[2], 2),
    ),
    "load_1m": SysMonitorSensorEntityDescription(
        key="load_1m",
        name="Load (1m)",
        icon=get_cpu_icon(),
        state_class=SensorStateClass.MEASUREMENT,
        value_load=lambda data: round(data[0], 2),
    ),
    "load_5m": SysMonitorSensorEntityDescription(
        key="load_5m",
        name="Load (5m)",
        icon=get_cpu_icon(),
        state_class=SensorStateClass.MEASUREMENT,
        value_load=lambda data: round(data[1], 2),
    ),
    "memory_free": SysMonitorSensorEntityDescription(
        key="memory_free",
        name="Memory free",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:memory",
        state_class=SensorStateClass.MEASUREMENT,
        value_memory=lambda data: round(data.available / 1024**2, 1),
    ),
    "memory_use": SysMonitorSensorEntityDescription(
        key="memory_use",
        name="Memory use",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:memory",
        state_class=SensorStateClass.MEASUREMENT,
        value_memory=lambda data: round((data.total - data.available) / 1024**2, 1),
    ),
    "memory_use_percent": SysMonitorSensorEntityDescription(
        key="memory_use_percent",
        name="Memory use (percent)",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:memory",
        state_class=SensorStateClass.MEASUREMENT,
        value_memory=lambda data: data.percent,
    ),
    "network_in": SysMonitorSensorEntityDescription(
        key="network_in",
        name="Network in",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:server-network",
        state_class=SensorStateClass.TOTAL_INCREASING,
        mandatory_arg=True,
        value_net_io=lambda data: round(data / 1024**2, 1),
    ),
    "network_out": SysMonitorSensorEntityDescription(
        key="network_out",
        name="Network out",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:server-network",
        state_class=SensorStateClass.TOTAL_INCREASING,
        mandatory_arg=True,
        value_net_io=lambda data: round(data / 1024**2, 1),
    ),
    "packets_in": SysMonitorSensorEntityDescription(
        key="packets_in",
        name="Packets in",
        icon="mdi:server-network",
        state_class=SensorStateClass.TOTAL_INCREASING,
        mandatory_arg=True,
        value_net_io=lambda data: data,
    ),
    "packets_out": SysMonitorSensorEntityDescription(
        key="packets_out",
        name="Packets out",
        icon="mdi:server-network",
        state_class=SensorStateClass.TOTAL_INCREASING,
        mandatory_arg=True,
        value_net_io=lambda data: data,
    ),
    "throughput_network_in": SysMonitorSensorEntityDescription(
        key="throughput_network_in",
        name="Network throughput in",
        native_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        mandatory_arg=True,
        value_net_throughput=lambda data: data,
    ),
    "throughput_network_out": SysMonitorSensorEntityDescription(
        key="throughput_network_out",
        name="Network throughput out",
        native_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        mandatory_arg=True,
        value_net_throughput=lambda data: data,
    ),
    "process": SysMonitorSensorEntityDescription(
        key="process",
        name="Process",
        icon=get_cpu_icon(),
        mandatory_arg=True,
        value_process=lambda data: STATE_ON if data is True else STATE_OFF,
    ),
    "processor_use": SysMonitorSensorEntityDescription(
        key="processor_use",
        name="Processor use",
        native_unit_of_measurement=PERCENTAGE,
        icon=get_cpu_icon(),
        state_class=SensorStateClass.MEASUREMENT,
        value_processor=lambda data: data,
    ),
    "processor_temperature": SysMonitorSensorEntityDescription(
        key="processor_temperature",
        name="Processor temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_cpu_temp=lambda data: data,
    ),
    "swap_free": SysMonitorSensorEntityDescription(
        key="swap_free",
        name="Swap free",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
        value_swap=lambda data: round(data.free / 1024**2, 1),
    ),
    "swap_use": SysMonitorSensorEntityDescription(
        key="swap_use",
        name="Swap use",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
        value_swap=lambda data: round(data.used / 1024**2, 1),
    ),
    "swap_use_percent": SysMonitorSensorEntityDescription(
        key="swap_use_percent",
        name="Swap use (percent)",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
        value_swap=lambda data: data.percent,
    ),
}


def check_required_arg(value: Any) -> Any:
    """Validate that the required "arg" for the sensor types that need it are set."""
    for sensor in value:
        sensor_type = sensor[CONF_TYPE]
        sensor_arg = sensor.get(CONF_ARG)

        if sensor_arg is None and SENSOR_TYPES[sensor_type].mandatory_arg:
            raise vol.RequiredFieldInvalid(
                f"Mandatory 'arg' is missing for sensor type '{sensor_type}'."
            )

    return value


def check_legacy_resource(resource: str, resources: set[str]) -> bool:
    """Return True if legacy resource was configured."""
    # This function to check legacy resources can be removed
    # once we are removing the import from YAML
    if resource in resources:
        _LOGGER.debug("Checking %s in %s returns True", resource, ", ".join(resources))
        return True
    _LOGGER.debug("Checking %s in %s returns False", resource, ", ".join(resources))
    return False


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_RESOURCES, default={CONF_TYPE: "disk_use"}): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required(CONF_TYPE): vol.In(SENSOR_TYPES),
                        vol.Optional(CONF_ARG): cv.string,
                    }
                )
            ],
            check_required_arg,
        )
    }
)

IO_COUNTER = {
    "network_out": 0,
    "network_in": 1,
    "packets_out": 2,
    "packets_in": 3,
    "throughput_network_out": 0,
    "throughput_network_in": 1,
}

IF_ADDRS_FAMILY = {"ipv4_address": socket.AF_INET, "ipv6_address": socket.AF_INET6}

# There might be additional keys to be added for different
# platforms / hardware combinations.
# Taken from last version of "glances" integration before they moved to
# a generic temperature sensor logic.
# https://github.com/home-assistant/core/blob/5e15675593ba94a2c11f9f929cdad317e27ce190/homeassistant/components/glances/sensor.py#L199
CPU_SENSOR_PREFIXES = [
    "amdgpu 1",
    "aml_thermal",
    "Core 0",
    "Core 1",
    "CPU Temperature",
    "CPU",
    "cpu-thermal 1",
    "cpu_thermal 1",
    "exynos-therm 1",
    "Package id 0",
    "Physical id 0",
    "radeon 1",
    "soc-thermal 1",
    "soc_thermal 1",
    "Tctl",
    "cpu0-thermal",
    "cpu0_thermal",
    "k10temp 1",
]


@dataclass
class SensorData:
    """Data for a sensor."""

    argument: Any
    state: str | datetime | None
    value: Any | None
    update_time: datetime | None
    last_exception: BaseException | None


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the system monitor sensors."""
    processes = [
        resource[CONF_ARG]
        for resource in config[CONF_RESOURCES]
        if resource[CONF_TYPE] == "process"
    ]
    legacy_config: list[dict[str, str]] = config[CONF_RESOURCES]
    resources = []
    for resource_conf in legacy_config:
        if (_type := resource_conf[CONF_TYPE]).startswith("disk_"):
            if (arg := resource_conf.get(CONF_ARG)) is None:
                resources.append(f"{_type}_/")
                continue
            resources.append(f"{_type}_{arg}")
            continue
        resources.append(f"{_type}_{resource_conf.get(CONF_ARG, '')}")
    _LOGGER.debug(
        "Importing config with processes: %s, resources: %s", processes, resources
    )

    # With removal of the import also cleanup legacy_resources logic in setup_entry
    # Also cleanup entry.options["resources"] which is only imported for legacy reasons

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={"processes": processes, "legacy_resources": resources},
        )
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up System Montor sensors based on a config entry."""
    entities = []
    sensor_registry: dict[tuple[str, str], SensorData] = {}
    legacy_resources: set[str] = set(entry.options.get("resources", []))
    loaded_resources: set[str] = set()
    disk_arguments = await hass.async_add_executor_job(get_all_disk_mounts)
    network_arguments = await hass.async_add_executor_job(get_all_network_interfaces)
    cpu_temperature = await hass.async_add_executor_job(_read_cpu_temperature)

    _LOGGER.debug("Setup from options %s", entry.options)

    for _type, sensor_description in SENSOR_TYPES.items():
        if _type.startswith("disk_"):
            for argument in disk_arguments:
                sensor_registry[(_type, argument)] = SensorData(
                    argument, None, None, None, None
                )
                is_enabled = check_legacy_resource(
                    f"{_type}_{argument}", legacy_resources
                )
                loaded_resources.add(slugify(f"{_type}_{argument}"))
                entities.append(
                    SystemMonitorSensor(
                        sensor_registry,
                        sensor_description,
                        entry.entry_id,
                        argument,
                        is_enabled,
                    )
                )
            continue

        if _type in NETWORK_TYPES:
            for argument in network_arguments:
                sensor_registry[(_type, argument)] = SensorData(
                    argument, None, None, None, None
                )
                is_enabled = check_legacy_resource(
                    f"{_type}_{argument}", legacy_resources
                )
                loaded_resources.add(slugify(f"{_type}_{argument}"))
                entities.append(
                    SystemMonitorSensor(
                        sensor_registry,
                        sensor_description,
                        entry.entry_id,
                        argument,
                        is_enabled,
                    )
                )
            continue

        # Verify if we can retrieve CPU / processor temperatures.
        # If not, do not create the entity and add a warning to the log
        if _type == "processor_temperature" and cpu_temperature is None:
            _LOGGER.warning("Cannot read CPU / processor temperature information")
            continue

        if _type == "process":
            _entry: dict[str, list] = entry.options.get(SENSOR_DOMAIN, {})
            for argument in _entry.get(CONF_PROCESS, []):
                sensor_registry[(_type, argument)] = SensorData(
                    argument, None, None, None, None
                )
                loaded_resources.add(slugify(f"{_type}_{argument}"))
                entities.append(
                    SystemMonitorSensor(
                        sensor_registry,
                        sensor_description,
                        entry.entry_id,
                        argument,
                        True,
                    )
                )
            continue

        sensor_registry[(_type, "")] = SensorData("", None, None, None, None)
        is_enabled = check_legacy_resource(f"{_type}_", legacy_resources)
        loaded_resources.add(f"{_type}_")
        entities.append(
            SystemMonitorSensor(
                sensor_registry,
                sensor_description,
                entry.entry_id,
                "",
                is_enabled,
            )
        )

    # Ensure legacy imported disk_* resources are loaded if they are not part
    # of mount points automatically discovered
    for resource in legacy_resources:
        if resource.startswith("disk_"):
            check_resource = slugify(resource)
            _LOGGER.debug(
                "Check resource %s already loaded in %s",
                check_resource,
                loaded_resources,
            )
            if check_resource not in loaded_resources:
                split_index = resource.rfind("_")
                _type = resource[:split_index]
                argument = resource[split_index + 1 :]
                _LOGGER.debug("Loading legacy %s with argument %s", _type, argument)
                sensor_registry[(_type, argument)] = SensorData(
                    argument, None, None, None, None
                )
                entities.append(
                    SystemMonitorSensor(
                        sensor_registry,
                        SENSOR_TYPES[_type],
                        entry.entry_id,
                        argument,
                        True,
                    )
                )

    scan_interval = DEFAULT_SCAN_INTERVAL
    await async_setup_sensor_registry_updates(hass, sensor_registry, scan_interval)
    async_add_entities(entities)


async def async_setup_sensor_registry_updates(
    hass: HomeAssistant,
    sensor_registry: dict[tuple[str, str], SensorData],
    scan_interval: timedelta,
) -> None:
    """Update the registry and create polling."""

    _update_lock = asyncio.Lock()

    def _update_sensors() -> None:
        """Update sensors and store the result in the registry."""
        for (type_, argument), data in sensor_registry.items():
            try:
                state, value, update_time = _update(type_, data)
            except Exception as ex:  # pylint: disable=broad-except
                _LOGGER.exception("Error updating sensor: %s (%s)", type_, argument)
                data.last_exception = ex
            else:
                data.state = state
                data.value = value
                data.update_time = update_time
                data.last_exception = None

        # Only fetch these once per iteration as we use the same
        # data source multiple times in _update
        _disk_usage.cache_clear()
        _swap_memory.cache_clear()
        _virtual_memory.cache_clear()
        _net_io_counters.cache_clear()
        _net_if_addrs.cache_clear()
        _getloadavg.cache_clear()

    async def _async_update_data(*_: Any) -> None:
        """Update all sensors in one executor jump."""
        if _update_lock.locked():
            _LOGGER.warning(
                (
                    "Updating systemmonitor took longer than the scheduled update"
                    " interval %s"
                ),
                scan_interval,
            )
            return

        async with _update_lock:
            await hass.async_add_executor_job(_update_sensors)
            async_dispatcher_send(hass, SIGNAL_SYSTEMMONITOR_UPDATE)

    polling_remover = async_track_time_interval(hass, _async_update_data, scan_interval)

    @callback
    def _async_stop_polling(*_: Any) -> None:
        polling_remover()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop_polling)

    await _async_update_data()


class SystemMonitorSensor(SensorEntity):
    """Implementation of a system monitor sensor."""

    should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        sensor_registry: dict[tuple[str, str], SensorData],
        sensor_description: SysMonitorSensorEntityDescription,
        entry_id: str,
        argument: str = "",
        legacy_enabled: bool = False,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = sensor_description
        self._attr_name: str = f"{sensor_description.name} {argument}".rstrip()
        self._attr_unique_id: str = slugify(f"{sensor_description.key}_{argument}")
        self._sensor_registry = sensor_registry
        self._argument: str = argument
        self._attr_entity_registry_enabled_default = legacy_enabled
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry_id)},
            manufacturer="System Monitor",
            name="System Monitor",
        )

    @property
    def native_value(self) -> str | datetime | None:
        """Return the state of the device."""
        return self.data.state

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.data.last_exception is None

    @property
    def data(self) -> SensorData:
        """Return registry entry for the data."""
        return self._sensor_registry[(self.entity_description.key, self._argument)]

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SYSTEMMONITOR_UPDATE, self.async_write_ha_state
            )
        )


def _update(  # noqa: C901
    type_: str, data: SensorData
) -> tuple[str | datetime | None, str | None, datetime | None]:
    """Get the latest system information."""
    state = None
    value = None
    update_time = None

    if type_ == "disk_use_percent":
        state = _disk_usage(data.argument).percent
    elif type_ == "disk_use":
        state = round(_disk_usage(data.argument).used / 1024**3, 1)
    elif type_ == "disk_free":
        state = round(_disk_usage(data.argument).free / 1024**3, 1)
    elif type_ == "memory_use_percent":
        state = _virtual_memory().percent
    elif type_ == "memory_use":
        virtual_memory = _virtual_memory()
        state = round((virtual_memory.total - virtual_memory.available) / 1024**2, 1)
    elif type_ == "memory_free":
        state = round(_virtual_memory().available / 1024**2, 1)
    elif type_ == "swap_use_percent":
        state = _swap_memory().percent
    elif type_ == "swap_use":
        state = round(_swap_memory().used / 1024**2, 1)
    elif type_ == "swap_free":
        state = round(_swap_memory().free / 1024**2, 1)
    elif type_ == "processor_use":
        state = round(psutil.cpu_percent(interval=None))
    elif type_ == "processor_temperature":
        state = _read_cpu_temperature()
    elif type_ == "process":
        state = STATE_OFF
        for proc in psutil.process_iter():
            try:
                if data.argument == proc.name():
                    state = STATE_ON
                    break
            except psutil.NoSuchProcess as err:
                _LOGGER.warning(
                    "Failed to load process with ID: %s, old name: %s",
                    err.pid,
                    err.name,
                )
    elif type_ in ("network_out", "network_in"):
        counters = _net_io_counters()
        if data.argument in counters:
            counter = counters[data.argument][IO_COUNTER[type_]]
            state = round(counter / 1024**2, 1)
        else:
            state = None
    elif type_ in ("packets_out", "packets_in"):
        counters = _net_io_counters()
        if data.argument in counters:
            state = counters[data.argument][IO_COUNTER[type_]]
        else:
            state = None
    elif type_ in ("throughput_network_out", "throughput_network_in"):
        counters = _net_io_counters()
        if data.argument in counters:
            counter = counters[data.argument][IO_COUNTER[type_]]
            now = dt_util.utcnow()
            if data.value and data.value < counter:
                state = round(
                    (counter - data.value)
                    / 1000**2
                    / (now - (data.update_time or now)).total_seconds(),
                    3,
                )
            else:
                state = None
            update_time = now
            value = counter
        else:
            state = None
    elif type_ in ("ipv4_address", "ipv6_address"):
        addresses = _net_if_addrs()
        if data.argument in addresses:
            for addr in addresses[data.argument]:
                if addr.family == IF_ADDRS_FAMILY[type_]:
                    state = addr.address
        else:
            state = None
    elif type_ == "last_boot":
        # Only update on initial setup
        if data.state is None:
            state = dt_util.utc_from_timestamp(psutil.boot_time())
        else:
            state = data.state
    elif type_ == "load_1m":
        state = round(_getloadavg()[0], 2)
    elif type_ == "load_5m":
        state = round(_getloadavg()[1], 2)
    elif type_ == "load_15m":
        state = round(_getloadavg()[2], 2)

    return state, value, update_time


@cache
def _disk_usage(path: str) -> Any:
    return psutil.disk_usage(path)


@cache
def _swap_memory() -> Any:
    return psutil.swap_memory()


@cache
def _virtual_memory() -> Any:
    return psutil.virtual_memory()


@cache
def _net_io_counters() -> Any:
    return psutil.net_io_counters(pernic=True)


@cache
def _net_if_addrs() -> Any:
    return psutil.net_if_addrs()


@cache
def _getloadavg() -> tuple[float, float, float]:
    return os.getloadavg()


def _read_cpu_temperature() -> float | None:
    """Attempt to read CPU / processor temperature."""
    try:
        temps = psutil.sensors_temperatures()
    except AttributeError:
        # Linux, macOS
        return None

    for name, entries in temps.items():
        for i, entry in enumerate(entries, start=1):
            # In case the label is empty (e.g. on Raspberry PI 4),
            # construct it ourself here based on the sensor key name.
            _label = f"{name} {i}" if not entry.label else entry.label
            # check both name and label because some systems embed cpu# in the
            # name, which makes label not match because label adds cpu# at end.
            if _label in CPU_SENSOR_PREFIXES or name in CPU_SENSOR_PREFIXES:
                return round(entry.current, 1)

    return None
