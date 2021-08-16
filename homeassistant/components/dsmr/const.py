"""Constants for the DSMR integration."""
from __future__ import annotations

import logging

from dsmr_parser import obis_references

from homeassistant.components.sensor import (
    STATE_CLASS_MEASUREMENT,
    STATE_CLASS_TOTAL_INCREASING,
)
from homeassistant.const import (
    DEVICE_CLASS_CURRENT,
    DEVICE_CLASS_ENERGY,
    DEVICE_CLASS_GAS,
    DEVICE_CLASS_POWER,
    DEVICE_CLASS_VOLTAGE,
)

from .models import DSMRSensorEntityDescription

DOMAIN = "dsmr"

LOGGER = logging.getLogger(__package__)

PLATFORMS = ["sensor"]

CONF_DSMR_VERSION = "dsmr_version"
CONF_RECONNECT_INTERVAL = "reconnect_interval"
CONF_PRECISION = "precision"
CONF_TIME_BETWEEN_UPDATE = "time_between_update"

CONF_SERIAL_ID = "serial_id"
CONF_SERIAL_ID_GAS = "serial_id_gas"

DEFAULT_DSMR_VERSION = "2.2"
DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_PRECISION = 3
DEFAULT_RECONNECT_INTERVAL = 30
DEFAULT_TIME_BETWEEN_UPDATE = 30

DATA_TASK = "task"

DEVICE_NAME_ENERGY = "Energy Meter"
DEVICE_NAME_GAS = "Gas Meter"

SENSORS: tuple[DSMRSensorEntityDescription, ...] = (
    DSMRSensorEntityDescription(
        key=obis_references.CURRENT_ELECTRICITY_USAGE,
        name="Power Consumption",
        device_class=DEVICE_CLASS_POWER,
        force_update=True,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.CURRENT_ELECTRICITY_DELIVERY,
        name="Power Production",
        device_class=DEVICE_CLASS_POWER,
        force_update=True,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.ELECTRICITY_ACTIVE_TARIFF,
        name="Power Tariff",
        icon="mdi:flash",
    ),
    DSMRSensorEntityDescription(
        key=obis_references.ELECTRICITY_USED_TARIFF_1,
        name="Energy Consumption (tarif 1)",
        device_class=DEVICE_CLASS_ENERGY,
        force_update=True,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.ELECTRICITY_USED_TARIFF_2,
        name="Energy Consumption (tarif 2)",
        force_update=True,
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.ELECTRICITY_DELIVERED_TARIFF_1,
        name="Energy Production (tarif 1)",
        force_update=True,
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.ELECTRICITY_DELIVERED_TARIFF_2,
        name="Energy Production (tarif 2)",
        force_update=True,
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_ACTIVE_POWER_L1_POSITIVE,
        name="Power Consumption Phase L1",
        device_class=DEVICE_CLASS_POWER,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_ACTIVE_POWER_L2_POSITIVE,
        name="Power Consumption Phase L2",
        device_class=DEVICE_CLASS_POWER,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_ACTIVE_POWER_L3_POSITIVE,
        name="Power Consumption Phase L3",
        device_class=DEVICE_CLASS_POWER,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_ACTIVE_POWER_L1_NEGATIVE,
        name="Power Production Phase L1",
        device_class=DEVICE_CLASS_POWER,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_ACTIVE_POWER_L2_NEGATIVE,
        name="Power Production Phase L2",
        device_class=DEVICE_CLASS_POWER,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_ACTIVE_POWER_L3_NEGATIVE,
        name="Power Production Phase L3",
        device_class=DEVICE_CLASS_POWER,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.SHORT_POWER_FAILURE_COUNT,
        name="Short Power Failure Count",
        entity_registry_enabled_default=False,
        icon="mdi:flash-off",
    ),
    DSMRSensorEntityDescription(
        key=obis_references.LONG_POWER_FAILURE_COUNT,
        name="Long Power Failure Count",
        entity_registry_enabled_default=False,
        icon="mdi:flash-off",
    ),
    DSMRSensorEntityDescription(
        key=obis_references.VOLTAGE_SAG_L1_COUNT,
        name="Voltage Sags Phase L1",
        entity_registry_enabled_default=False,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.VOLTAGE_SAG_L2_COUNT,
        name="Voltage Sags Phase L2",
        entity_registry_enabled_default=False,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.VOLTAGE_SAG_L3_COUNT,
        name="Voltage Sags Phase L3",
        entity_registry_enabled_default=False,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.VOLTAGE_SWELL_L1_COUNT,
        name="Voltage Swells Phase L1",
        entity_registry_enabled_default=False,
        icon="mdi:pulse",
    ),
    DSMRSensorEntityDescription(
        key=obis_references.VOLTAGE_SWELL_L2_COUNT,
        name="Voltage Swells Phase L2",
        entity_registry_enabled_default=False,
        icon="mdi:pulse",
    ),
    DSMRSensorEntityDescription(
        key=obis_references.VOLTAGE_SWELL_L3_COUNT,
        name="Voltage Swells Phase L3",
        entity_registry_enabled_default=False,
        icon="mdi:pulse",
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_VOLTAGE_L1,
        name="Voltage Phase L1",
        device_class=DEVICE_CLASS_VOLTAGE,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_VOLTAGE_L2,
        name="Voltage Phase L2",
        device_class=DEVICE_CLASS_VOLTAGE,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_VOLTAGE_L3,
        name="Voltage Phase L3",
        device_class=DEVICE_CLASS_VOLTAGE,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_CURRENT_L1,
        name="Current Phase L1",
        device_class=DEVICE_CLASS_CURRENT,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_CURRENT_L2,
        name="Current Phase L2",
        device_class=DEVICE_CLASS_CURRENT,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.INSTANTANEOUS_CURRENT_L3,
        name="Current Phase L3",
        device_class=DEVICE_CLASS_CURRENT,
        entity_registry_enabled_default=False,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.LUXEMBOURG_ELECTRICITY_USED_TARIFF_GLOBAL,
        name="Energy Consumption (total)",
        dsmr_versions={"5L"},
        force_update=True,
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.LUXEMBOURG_ELECTRICITY_DELIVERED_TARIFF_GLOBAL,
        name="Energy Production (total)",
        dsmr_versions={"5L"},
        force_update=True,
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.ELECTRICITY_IMPORTED_TOTAL,
        name="Energy Consumption (total)",
        dsmr_versions={"2.2", "4", "5", "5B"},
        force_update=True,
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.HOURLY_GAS_METER_READING,
        name="Gas Consumption",
        dsmr_versions={"4", "5", "5L"},
        is_gas=True,
        force_update=True,
        icon="mdi:fire",
        device_class=DEVICE_CLASS_GAS,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.BELGIUM_HOURLY_GAS_METER_READING,
        name="Gas Consumption",
        dsmr_versions={"5B"},
        is_gas=True,
        force_update=True,
        icon="mdi:fire",
        device_class=DEVICE_CLASS_GAS,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
    DSMRSensorEntityDescription(
        key=obis_references.GAS_METER_READING,
        name="Gas Consumption",
        dsmr_versions={"2.2"},
        is_gas=True,
        force_update=True,
        icon="mdi:fire",
        device_class=DEVICE_CLASS_GAS,
        state_class=STATE_CLASS_TOTAL_INCREASING,
    ),
)
