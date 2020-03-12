"""Support for Synology DSM Sensors."""
from datetime import timedelta
from typing import Dict

from SynologyDSM import SynologyDSM

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    CONF_API_VERSION,
    CONF_DISKS,
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    DATA_MEGABYTES,
    DATA_RATE_KILOBYTES_PER_SECOND,
    TEMP_CELSIUS,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect, dispatcher_send
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import HomeAssistantType

from .const import (
    CONF_VOLUMES,
    DEFAULT_DSM_VERSION,
    SERVICE_UPDATE,
    STORAGE_DISK_SENSORS,
    STORAGE_VOL_SENSORS,
    TEMP_SENSORS_KEYS,
    UTILISATION_SENSORS,
)

ATTRIBUTION = "Data provided by Synology"

SCAN_INTERVAL = timedelta(minutes=15)


async def async_setup_entry(
    hass: HomeAssistantType, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up the Synology NAS Sensor."""
    name = entry.data[CONF_NAME]
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    unit = hass.config.units.temperature_unit
    use_ssl = entry.data[CONF_SSL]
    api_version = entry.data.get(CONF_API_VERSION, DEFAULT_DSM_VERSION)

    api = SynoApi(hass, host, port, username, password, unit, use_ssl, api_version)

    await hass.async_add_executor_job(api.update)

    sensors = [
        SynoNasUtilSensor(api, name, sensor_type, UTILISATION_SENSORS[sensor_type])
        for sensor_type in UTILISATION_SENSORS
    ]

    # Handle all volumes
    if api.storage.volumes is not None:
        for volume in entry.data.get(CONF_VOLUMES, api.storage.volumes):
            sensors += [
                SynoNasStorageSensor(
                    api, name, sensor_type, STORAGE_VOL_SENSORS[sensor_type], volume
                )
                for sensor_type in STORAGE_VOL_SENSORS
            ]

    # Handle all disks
    if api.storage.disks is not None:
        for disk in entry.data.get(CONF_DISKS, api.storage.disks):
            sensors += [
                SynoNasStorageSensor(
                    api, name, sensor_type, STORAGE_DISK_SENSORS[sensor_type], disk
                )
                for sensor_type in STORAGE_DISK_SENSORS
            ]

    async_track_time_interval(hass, api.update, SCAN_INTERVAL)

    async_add_entities(sensors, True)


class SynoApi:
    """Class to interface with Synology DSM API."""

    def __init__(
        self,
        hass: HomeAssistantType,
        host: str,
        port: int,
        username: str,
        password: str,
        temp_unit: str,
        use_ssl: bool,
        api_version: int,
    ):
        """Initialize the API wrapper class."""
        self._hass = hass
        self.temp_unit = temp_unit

        self._api = SynologyDSM(
            host, port, username, password, use_ssl, dsm_version=api_version
        )

        self.utilisation = self._api.utilisation
        self.storage = self._api.storage

    def update(self, now=None):
        """Update function for updating API information."""
        self._api.update()
        dispatcher_send(self._hass, SERVICE_UPDATE)


class SynoNasSensor(Entity):
    """Representation of a Synology NAS Sensor."""

    def __init__(
        self,
        api: SynoApi,
        name: str,
        sensor_type: str,
        sensor_info: Dict[str, str],
        monitored_device: str = None,
    ):
        """Initialize the sensor."""
        self.sensor_type = sensor_type
        self._name = f"{name} {sensor_info[0]}"
        self._unit = sensor_info[1]
        self._icon = sensor_info[2]
        self.monitored_device = monitored_device
        self._api = api

        if self.monitored_device is not None:
            self._name = f"{self._name} ({self.monitored_device})"

        self._unsub_dispatcher = None

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._name

    @property
    def name(self) -> str:
        """Return the name."""
        return self._name

    @property
    def icon(self):
        """Return the icon."""
        return self._icon

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        if self.sensor_type in TEMP_SENSORS_KEYS:
            return self._api.temp_unit
        return self._unit

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {ATTR_ATTRIBUTION: ATTRIBUTION}

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False

    async def async_added_to_hass(self):
        """Register state update callback."""
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, SERVICE_UPDATE, self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self):
        """Clean up after entity before removal."""
        self._unsub_dispatcher()


class SynoNasUtilSensor(SynoNasSensor):
    """Representation a Synology Utilisation Sensor."""

    @property
    def state(self):
        """Return the state."""
        if self._unit == DATA_RATE_KILOBYTES_PER_SECOND or self._unit == DATA_MEGABYTES:
            attr = getattr(self._api.utilisation, self.sensor_type)(False)

            if attr is None:
                return None

            if self._unit == DATA_RATE_KILOBYTES_PER_SECOND:
                return round(attr / 1024.0, 1)
            if self._unit == DATA_MEGABYTES:
                return round(attr / 1024.0 / 1024.0, 1)
        else:
            return getattr(self._api.utilisation, self.sensor_type)


class SynoNasStorageSensor(SynoNasSensor):
    """Representation a Synology Storage Sensor."""

    @property
    def state(self):
        """Return the state."""
        if self.monitored_device is not None:
            if self.sensor_type in TEMP_SENSORS_KEYS:
                attr = getattr(self._api.storage, self.sensor_type)(
                    self.monitored_device
                )

                if attr is None:
                    return None

                if self._api.temp_unit == TEMP_CELSIUS:
                    return attr

                return round(attr * 1.8 + 32.0, 1)

            return getattr(self._api.storage, self.sensor_type)(self.monitored_device)
        return None
