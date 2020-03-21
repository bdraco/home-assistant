"""
Sensor to collect the reference daily prices of electricity ('PVPC') in Spain.

For more details about this platform, please refer to the documentation at
https://www.home-assistant.io/integrations/pvpc_hourly_pricing/
"""
from datetime import timedelta
import logging
from random import randint
from typing import Optional

from aiopvpc import PVPCData

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_time_change,
)
from homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.util.dt as dt_util

from .const import ATTR_TARIFF

_LOGGER = logging.getLogger(__name__)

ATTR_PRICE = "price"
ICON = "mdi:currency-eur"
UNIT = "€/kWh"

_DEFAULT_TIMEOUT = 10


async def async_setup_entry(
    hass: HomeAssistant, config_entry: config_entries.ConfigEntry, async_add_entities
):
    """Set up the electricity price sensor from config_entry."""
    name = config_entry.data[CONF_NAME]
    pvpc_data_handler = PVPCData(
        tariff=config_entry.data[ATTR_TARIFF],
        local_timezone=hass.config.time_zone,
        websession=async_get_clientsession(hass),
        logger=_LOGGER,
        timeout=_DEFAULT_TIMEOUT,
    )
    async_add_entities(
        [ElecPriceSensor(name, config_entry.unique_id, pvpc_data_handler)], False
    )


class ElecPriceSensor(RestoreEntity):
    """Class to hold the prices of electricity as a sensor."""

    unit_of_measurement = UNIT
    icon = ICON
    should_poll = False

    def __init__(self, name, unique_id, pvpc_data_handler):
        """Initialize the sensor object."""
        self._name = name
        self._unique_id = unique_id
        self._pvpc_data = pvpc_data_handler
        self._num_retries = 0
        self._pvpc_data_available = True
        self._hourly_tracker = None
        self._price_tracker = None

    async def async_will_remove_from_hass(self) -> None:
        """Cancel listeners for sensor updates."""
        self._price_tracker()

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state:
            self._pvpc_data.state = state.state

        # Update prices at random time, 2 times/hour (don't want to upset API)
        random_minute = randint(1, 29)
        mins_update = [random_minute, random_minute + 30]
        self._price_tracker = async_track_time_change(
            self.hass,
            self._async_update_and_write_state,
            second=[0],
            minute=mins_update,
        )
        _LOGGER.debug(
            "Setup of price sensor %s (%s) with tariff '%s', "
            "updating prices each hour at %s min",
            self.name,
            self.entity_id,
            self._pvpc_data.tariff,
            mins_update,
        )
        await self._async_update_and_write_state(dt_util.utcnow())

    @property
    def unique_id(self) -> Optional[str]:
        """Return a unique ID."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._pvpc_data.state

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._pvpc_data_available

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._pvpc_data.attributes

    async def async_update(self, *args):
        """Update the sensor state from the API."""
        await self._async_update(dt_util.utcnow())

    async def _async_update_and_write_state(self, now):
        """Update the sensor state and write it to ha if successful."""
        if await self._async_update(now):
            self.async_write_ha_state()

    async def _async_update(self, now):
        """Update electricity prices from the ESIOS API."""
        if await self._pvpc_data.async_update_prices(now):
            if not self._pvpc_data.source_available:
                _LOGGER.warning(
                    "%s: component has recovered data access", self.entity_id
                )
                self._pvpc_data.source_available = True
                self._num_retries = 0

            self._pvpc_data.process_state_and_attributes(now)
            return True

        if not self._pvpc_data_available:
            _LOGGER.debug("%s: data source is not available", self.entity_id)
            return False

        self._num_retries += 1
        if self._num_retries > 2:
            _LOGGER.warning(
                "%s: repeated bad data update, mark component as unavailable source",
                self.entity_id,
            )
            self._pvpc_data_available = False
            return False

        retry_delay = 2 * self._pvpc_data.timeout
        _LOGGER.debug(
            "%s: Bad update[retry:%d], will try again in %d s",
            self.entity_id,
            self._num_retries,
            retry_delay,
        )
        async_track_point_in_time(
            self.hass,
            self._async_update,
            dt_util.now() + timedelta(seconds=retry_delay),
        )
        return False
