"""Support for monitoring the local system."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache, lru_cache
import logging
import socket
import sys
from typing import Any, Literal, Generic

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
    PERCENTAGE,
    STATE_OFF,
    STATE_ON,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType, StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util, slugify

from .const import CONF_PROCESS, DOMAIN, NET_IO_TYPES
from .coordinator import (
    MonitorCoordinator,
    SystemMonitorBootTimeCoordinator,
    SystemMonitorCPUtempCoordinator,
    SystemMonitorDiskCoordinator,
    SystemMonitorLoadCoordinator,
    SystemMonitorMemoryCoordinator,
    SystemMonitorNetAddrCoordinator,
    SystemMonitorNetIOCoordinator,
    SystemMonitorProcessCoordinator,
    SystemMonitorProcessorCoordinator,
    SystemMonitorSwapCoordinator,
    dataT,
)
from .util import get_all_disk_mounts, get_all_network_interfaces, read_cpu_temperature

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
class SysMonitorSensorEntityDescriptionMixin(Generic[dataT]):
    """Mixin for System Monitor sensor entities."""

    value_fn: Callable[[SystemMonitorSensor[dataT]], StateType | datetime] = get_update


@dataclass(frozen=True)
class SysMonitorSensorEntityDescription(
    SysMonitorSensorEntityDescriptionMixin[dataT],
    SensorEntityDescription,
):
    """Describes System Monitor sensor entities."""

    mandatory_arg: bool = False


SENSOR_TYPES: dict[str, SysMonitorSensorEntityDescription[Any]] = {
    "disk_free": SysMonitorSensorEntityDescription[sdiskusage](
        key="disk_free",
        name="Disk free",
        native_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "disk_use": SysMonitorSensorEntityDescription[sdiskusage](
        key="disk_use",
        name="Disk use",
        native_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "disk_use_percent": SysMonitorSensorEntityDescription[sdiskusage](
        key="disk_use_percent",
        name="Disk use (percent)",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "ipv4_address": SysMonitorSensorEntityDescription[str](
        key="ipv4_address",
        name="IPv4 address",
        icon="mdi:ip-network",
        mandatory_arg=True,
    ),
    "ipv6_address": SysMonitorSensorEntityDescription[str](
        key="ipv6_address",
        name="IPv6 address",
        icon="mdi:ip-network",
        mandatory_arg=True,
    ),
    "last_boot": SysMonitorSensorEntityDescription[datetime](
        key="last_boot",
        name="Last boot",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    "load_15m": SysMonitorSensorEntityDescription[tuple[float, float, float]](
        key="load_15m",
        name="Load (15m)",
        icon=get_cpu_icon(),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "load_1m": SysMonitorSensorEntityDescription[tuple[float, float, float]](
        key="load_1m",
        name="Load (1m)",
        icon=get_cpu_icon(),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "load_5m": SysMonitorSensorEntityDescription[tuple[float, float, float]](
        key="load_5m",
        name="Load (5m)",
        icon=get_cpu_icon(),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "memory_free": SysMonitorSensorEntityDescription[svmem](
        key="memory_free",
        name="Memory free",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:memory",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "memory_use": SysMonitorSensorEntityDescription[svmem](
        key="memory_use",
        name="Memory use",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:memory",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "memory_use_percent": SysMonitorSensorEntityDescription[svmem](
        key="memory_use_percent",
        name="Memory use (percent)",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:memory",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "network_in": SysMonitorSensorEntityDescription[int](
        key="network_in",
        name="Network in",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:server-network",
        state_class=SensorStateClass.TOTAL_INCREASING,
        mandatory_arg=True,
    ),
    "network_out": SysMonitorSensorEntityDescription[int](
        key="network_out",
        name="Network out",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:server-network",
        state_class=SensorStateClass.TOTAL_INCREASING,
        mandatory_arg=True,
    ),
    "packets_in": SysMonitorSensorEntityDescription[int](
        key="packets_in",
        name="Packets in",
        icon="mdi:server-network",
        state_class=SensorStateClass.TOTAL_INCREASING,
        mandatory_arg=True,
    ),
    "packets_out": SysMonitorSensorEntityDescription[int](
        key="packets_out",
        name="Packets out",
        icon="mdi:server-network",
        state_class=SensorStateClass.TOTAL_INCREASING,
        mandatory_arg=True,
    ),
    "throughput_network_in": SysMonitorSensorEntityDescription[float | None](
        key="throughput_network_in",
        name="Network throughput in",
        native_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        mandatory_arg=True,
    ),
    "throughput_network_out": SysMonitorSensorEntityDescription[float | None](
        key="throughput_network_out",
        name="Network throughput out",
        native_unit_of_measurement=UnitOfDataRate.MEGABYTES_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        mandatory_arg=True,
    ),
    "process": SysMonitorSensorEntityDescription[bool](
        key="process",
        name="Process",
        icon=get_cpu_icon(),
        mandatory_arg=True,
    ),
    "processor_use": SysMonitorSensorEntityDescription[float](
        key="processor_use",
        name="Processor use",
        native_unit_of_measurement=PERCENTAGE,
        icon=get_cpu_icon(),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "processor_temperature": SysMonitorSensorEntityDescription[float](
        key="processor_temperature",
        name="Processor temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "swap_free": SysMonitorSensorEntityDescription[sswap](
        key="swap_free",
        name="Swap free",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "swap_use": SysMonitorSensorEntityDescription[sswap](
        key="swap_use",
        name="Swap use",
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "swap_use_percent": SysMonitorSensorEntityDescription[sswap](
        key="swap_use_percent",
        name="Swap use (percent)",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:harddisk",
        state_class=SensorStateClass.MEASUREMENT,
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


async def async_setup_entry(  # noqa: C901
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up System Montor sensors based on a config entry."""
    entities: list[SystemMonitorSensor] = []
    legacy_resources: set[str] = set(entry.options.get("resources", []))
    loaded_resources: set[str] = set()
    disk_arguments = await hass.async_add_executor_job(get_all_disk_mounts)
    network_arguments = await hass.async_add_executor_job(get_all_network_interfaces)
    cpu_temperature = await hass.async_add_executor_job(read_cpu_temperature)

    disk_coordinators: dict[str, SystemMonitorDiskCoordinator] = {}
    for argument in disk_arguments:
        disk_coordinators[argument] = SystemMonitorDiskCoordinator(hass, argument)
    swap_coordinator = SystemMonitorSwapCoordinator(hass)
    memory_coordinator = SystemMonitorMemoryCoordinator(hass)
    net_io_coordinator = SystemMonitorNetIOCoordinator(hass)
    net_addr_coordinator = SystemMonitorNetAddrCoordinator(hass)
    system_load_coordinator = SystemMonitorLoadCoordinator(hass)
    processor_coordinator = SystemMonitorProcessorCoordinator(hass)
    boot_time_coordinator = SystemMonitorBootTimeCoordinator(hass)
    process_coordinator = SystemMonitorProcessCoordinator(hass)
    cpu_temp_coordinator = SystemMonitorCPUtempCoordinator(hass)

    for argument in disk_arguments:
        disk_coordinators[argument] = SystemMonitorDiskCoordinator(hass, argument)

    _LOGGER.debug("Setup from options %s", entry.options)

    for _type, sensor_description in SENSOR_TYPES.items():
        if _type.startswith("disk_"):
            for argument in disk_arguments:
                is_enabled = check_legacy_resource(
                    f"{_type}_{argument}", legacy_resources
                )
                loaded_resources.add(slugify(f"{_type}_{argument}"))
                entities.append(
                    SystemMonitorSensor(
                        disk_coordinators[argument],
                        sensor_description,
                        entry.entry_id,
                        argument,
                        is_enabled,
                    )
                )
            continue

        if _type.startswith("ipv"):
            for argument in network_arguments:
                is_enabled = check_legacy_resource(
                    f"{_type}_{argument}", legacy_resources
                )
                loaded_resources.add(f"{_type}_{argument}")
                entities.append(
                    SystemMonitorSensor(
                        net_addr_coordinator,
                        sensor_description,
                        entry.entry_id,
                        argument,
                        is_enabled,
                    )
                )
            continue

        if _type == "last_boot":
            argument = ""
            is_enabled = check_legacy_resource(f"{_type}_{argument}", legacy_resources)
            loaded_resources.add(f"{_type}_{argument}")
            entities.append(
                SystemMonitorSensor(
                    boot_time_coordinator,
                    sensor_description,
                    entry.entry_id,
                    argument,
                    is_enabled,
                )
            )
            continue

        if _type.startswith("load_"):
            argument = ""
            is_enabled = check_legacy_resource(f"{_type}_{argument}", legacy_resources)
            loaded_resources.add(f"{_type}_{argument}")
            entities.append(
                SystemMonitorSensor(
                    system_load_coordinator,
                    sensor_description,
                    entry.entry_id,
                    argument,
                    is_enabled,
                )
            )
            continue

        if _type.startswith("memory_"):
            argument = ""
            is_enabled = check_legacy_resource(f"{_type}_{argument}", legacy_resources)
            loaded_resources.add(f"{_type}_{argument}")
            entities.append(
                SystemMonitorSensor(
                    memory_coordinator,
                    sensor_description,
                    entry.entry_id,
                    argument,
                    is_enabled,
                )
            )

        if _type in NET_IO_TYPES:
            for argument in network_arguments:
                is_enabled = check_legacy_resource(
                    f"{_type}_{argument}", legacy_resources
                )
                loaded_resources.add(f"{_type}_{argument}")
                entities.append(
                    SystemMonitorSensor(
                        net_io_coordinator,
                        sensor_description,
                        entry.entry_id,
                        argument,
                        is_enabled,
                    )
                )
            continue

        if _type == "process":
            _entry = entry.options.get(SENSOR_DOMAIN, {})
            for argument in _entry.get(CONF_PROCESS, []):
                loaded_resources.add(slugify(f"{_type}_{argument}"))
                entities.append(
                    SystemMonitorSensor(
                        process_coordinator,
                        sensor_description,
                        entry.entry_id,
                        argument,
                        True,
                    )
                )
            continue

        if _type == "processor_use":
            argument = ""
            is_enabled = check_legacy_resource(f"{_type}_{argument}", legacy_resources)
            loaded_resources.add(f"{_type}_{argument}")
            entities.append(
                SystemMonitorSensor(
                    processor_coordinator,
                    sensor_description,
                    entry.entry_id,
                    argument,
                    is_enabled,
                )
            )
            continue

        if _type == "processor_temperature":
            if not cpu_temperature:
                # Don't load processor temperature sensor if we can't read it.
                continue
            argument = ""
            is_enabled = check_legacy_resource(f"{_type}_{argument}", legacy_resources)
            loaded_resources.add(f"{_type}_{argument}")
            entities.append(
                SystemMonitorSensor(
                    cpu_temp_coordinator,
                    sensor_description,
                    entry.entry_id,
                    argument,
                    is_enabled,
                )
            )
            continue

        if _type.startswith("swap_"):
            argument = ""
            is_enabled = check_legacy_resource(f"{_type}_{argument}", legacy_resources)
            loaded_resources.add(f"{_type}_{argument}")
            entities.append(
                SystemMonitorSensor(
                    swap_coordinator,
                    sensor_description,
                    entry.entry_id,
                    argument,
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
                if not disk_coordinators.get(argument):
                    disk_coordinators[argument] = SystemMonitorDiskCoordinator(
                        hass, argument
                    )
                entities.append(
                    SystemMonitorSensor(
                        disk_coordinators[argument],
                        SENSOR_TYPES[_type],
                        entry.entry_id,
                        argument,
                        True,
                    )
                )

    for coordinator in disk_coordinators.values():
        await coordinator.async_request_refresh()
    await boot_time_coordinator.async_request_refresh()
    await cpu_temp_coordinator.async_request_refresh()
    await memory_coordinator.async_request_refresh()
    await net_addr_coordinator.async_request_refresh()
    await net_io_coordinator.async_request_refresh()
    await process_coordinator.async_request_refresh()
    await processor_coordinator.async_request_refresh()
    await swap_coordinator.async_request_refresh()
    await system_load_coordinator.async_request_refresh()

    async_add_entities(entities)


class SystemMonitorSensor(CoordinatorEntity[MonitorCoordinator[dataT]], SensorEntity):
    """Implementation of a system monitor sensor."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    entity_description: SysMonitorSensorEntityDescription

    def __init__(
        self,
        coordinator: MonitorCoordinator,
        sensor_description: SysMonitorSensorEntityDescription,
        entry_id: str,
        argument: str,
        legacy_enabled: bool = False,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = sensor_description
        self._attr_name: str = f"{sensor_description.name} {argument}".rstrip()
        self._attr_unique_id: str = slugify(f"{sensor_description.key}_{argument}")
        self._attr_entity_registry_enabled_default = legacy_enabled
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry_id)},
            manufacturer="System Monitor",
            name="System Monitor",
        )
        self.argument = argument
        self.value: float | None = None
        self.update_time: datetime | None = None

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state."""
        return self.entity_description.value_fn(self)
