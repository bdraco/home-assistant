"""Tests for ScreenLogic integration init."""
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.screenlogic import DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import slugify

from .conftest import (
    MOCK_ADAPTER_MAC,
    MOCK_ADAPTER_NAME,
)

from tests.common import MockConfigEntry


@dataclass
class EntityMigrationData:
    """Class to organize minimum entity data."""

    old_name: str
    old_key: str
    new_name: str
    new_key: str
    domain: str


TEST_MIGRATING_ENTITIES = [
    EntityMigrationData(
        "Chemistry Alarm",
        "chem_alarm",
        "Active Alert",
        "active_alert",
        BINARY_SENSOR_DOMAIN,
    ),
    EntityMigrationData(
        "Pool Pump Current Watts",
        "currentWatts_0",
        "Pool Pump Watts Now",
        "pump_0_watts_now",
        SENSOR_DOMAIN,
    ),
    EntityMigrationData(
        "SCG Status",
        "scg_status",
        "Chlorinator",
        "scg_state",
        BINARY_SENSOR_DOMAIN,
    ),
    EntityMigrationData(
        "Non-Migrating Sensor",
        "nonmigrating",
        "Non-Migrating Sensor",
        "nonmigrating",
        SENSOR_DOMAIN,
    ),
    EntityMigrationData(
        "Missing Migration Device",
        "missing_device",
        "Missing Migration Device",
        "missing_device",
        BINARY_SENSOR_DOMAIN,
    ),
    EntityMigrationData(
        "Old Sensor",
        "old_sensor",
        "Old Sensor",
        "old_sensor",
        SENSOR_DOMAIN,
    ),
]

TEST_EXISTING_ENTRY = {
    "domain": SENSOR_DOMAIN,
    "platform": DOMAIN,
    "unique_id": f"{MOCK_ADAPTER_MAC}_existing",
    "suggested_object_id": f"{MOCK_ADAPTER_NAME} Existing Sensor",
    "disabled_by": None,
    "has_entity_name": True,
    "original_name": "Existing Sensor",
}


@pytest.mark.parametrize(
    ("entity_def", "ent_data"),
    [
        (
            {
                "domain": ent_data.domain,
                "platform": DOMAIN,
                "unique_id": f"{MOCK_ADAPTER_MAC}_{ent_data.old_key}",
                "suggested_object_id": f"{MOCK_ADAPTER_NAME} {ent_data.old_name}",
                "disabled_by": None,
                "has_entity_name": True,
                "original_name": ent_data.old_name,
            },
            ent_data,
        )
        for ent_data in TEST_MIGRATING_ENTITIES
    ],
)
async def test_async_migrate_entries(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_gateway,
    entity_def: dict,
    ent_data: EntityMigrationData,
) -> None:
    """Test migration to new entity names."""

    mock_config_entry.add_to_hass(hass)

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    device: dr.DeviceEntry = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, MOCK_ADAPTER_MAC)},
    )

    entity_registry.async_get_or_create(
        **TEST_EXISTING_ENTRY, device_id=device.id, config_entry=mock_config_entry
    )

    entity: er.RegistryEntry = entity_registry.async_get_or_create(
        **entity_def, device_id=device.id, config_entry=mock_config_entry
    )

    old_eid = f"{ent_data.domain}.{slugify(f'{MOCK_ADAPTER_NAME} {ent_data.old_name}')}"
    old_uid = f"{MOCK_ADAPTER_MAC}_{ent_data.old_key}"
    new_eid = f"{ent_data.domain}.{slugify(f'{MOCK_ADAPTER_NAME} {ent_data.new_name}')}"
    new_uid = f"{MOCK_ADAPTER_MAC}_{ent_data.new_key}"

    assert entity.unique_id == old_uid
    assert entity.entity_id == old_eid
    with patch.dict(
        "homeassistant.components.screenlogic.data.ENTITY_MIGRATIONS",
        {
            "missing_device": {
                "new_key": "state",
                "old_name": "Missing Migration Device",
                "new_name": "Bad ENTITY_MIGRATIONS Entry",
            },
            "old_sensor": {
                "new_key": "existing",
                "old_name": "Old",
                "new_name": "Existing",
            },
        },
    ), patch(
        "homeassistant.components.screenlogic.async_discover_gateways_by_unique_id",
        return_value={},
    ), patch(
        "homeassistant.components.screenlogic.ScreenLogicGateway",
        return_value=mock_gateway,
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    entity_migrated = entity_registry.async_get(new_eid)
    assert entity_migrated
    assert entity_migrated.entity_id == new_eid
    assert entity_migrated.unique_id == new_uid
    assert entity_migrated.original_name == ent_data.new_name
