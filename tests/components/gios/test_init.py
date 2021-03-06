"""Test init of GIOS integration."""
import json
from unittest.mock import patch

from homeassistant.components.gios.const import DOMAIN
from homeassistant.config_entries import (
    ENTRY_STATE_LOADED,
    ENTRY_STATE_NOT_LOADED,
    ENTRY_STATE_SETUP_RETRY,
)
from homeassistant.const import STATE_UNAVAILABLE

from . import STATIONS

from tests.common import MockConfigEntry, load_fixture, mock_device_registry
from tests.components.gios import init_integration


async def test_async_setup_entry(hass):
    """Test a successful setup entry."""
    await init_integration(hass)

    state = hass.states.get("air_quality.home")
    assert state is not None
    assert state.state != STATE_UNAVAILABLE
    assert state.state == "4"


async def test_config_not_ready(hass):
    """Test for setup failure if connection to GIOS is missing."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id=123,
        data={"station_id": 123, "name": "Home"},
    )

    with patch(
        "homeassistant.components.gios.Gios._get_stations",
        side_effect=ConnectionError(),
    ):
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        assert entry.state == ENTRY_STATE_SETUP_RETRY


async def test_unload_entry(hass):
    """Test successful unload of entry."""
    entry = await init_integration(hass)

    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert entry.state == ENTRY_STATE_LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state == ENTRY_STATE_NOT_LOADED
    assert not hass.data.get(DOMAIN)


async def test_migrate_device_and_config_entry(hass):
    """Test device_info identifiers and config entry migration."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id=123,
        data={
            "station_id": 123,
            "name": "Home",
        },
    )

    indexes = json.loads(load_fixture("gios/indexes.json"))
    station = json.loads(load_fixture("gios/station.json"))
    sensors = json.loads(load_fixture("gios/sensors.json"))

    with patch(
        "homeassistant.components.gios.Gios._get_stations", return_value=STATIONS
    ), patch(
        "homeassistant.components.gios.Gios._get_station",
        return_value=station,
    ), patch(
        "homeassistant.components.gios.Gios._get_all_sensors",
        return_value=sensors,
    ), patch(
        "homeassistant.components.gios.Gios._get_indexes", return_value=indexes
    ):
        config_entry.add_to_hass(hass)

        device_reg = mock_device_registry(hass)
        device_entry = device_reg.async_get_or_create(
            config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, 123)}
        )

        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        migrated_device_entry = device_reg.async_get_or_create(
            config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, "123")}
        )
        assert device_entry.id == migrated_device_entry.id
