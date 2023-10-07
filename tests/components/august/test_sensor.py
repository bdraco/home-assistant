"""The sensor tests for the august platform."""
from typing import Any

from homeassistant import core as ha
from homeassistant.const import (
    ATTR_ENTITY_PICTURE,
    ATTR_UNIT_OF_MEASUREMENT,
    PERCENTAGE,
    STATE_UNKNOWN,
)
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import entity_registry as er

from .mocks import (
    _create_august_with_devices,
    _mock_activities_from_fixture,
    _mock_doorbell_from_fixture,
    _mock_doorsense_enabled_august_lock_detail,
    _mock_lock_from_fixture,
)

from tests.common import mock_restore_cache_with_extra_data


async def test_create_doorbell(hass: HomeAssistant) -> None:
    """Test creation of a doorbell."""
    doorbell_one = await _mock_doorbell_from_fixture(hass, "get_doorbell.json")
    await _create_august_with_devices(hass, [doorbell_one])

    sensor_k98gidt45gul_name_battery = hass.states.get(
        "sensor.k98gidt45gul_name_battery"
    )
    assert sensor_k98gidt45gul_name_battery.state == "96"
    assert (
        sensor_k98gidt45gul_name_battery.attributes["unit_of_measurement"] == PERCENTAGE
    )


async def test_create_doorbell_offline(hass: HomeAssistant) -> None:
    """Test creation of a doorbell that is offline."""
    doorbell_one = await _mock_doorbell_from_fixture(hass, "get_doorbell.offline.json")
    await _create_august_with_devices(hass, [doorbell_one])
    entity_registry = er.async_get(hass)

    sensor_tmt100_name_battery = hass.states.get("sensor.tmt100_name_battery")
    assert sensor_tmt100_name_battery.state == "81"
    assert sensor_tmt100_name_battery.attributes["unit_of_measurement"] == PERCENTAGE

    entry = entity_registry.async_get("sensor.tmt100_name_battery")
    assert entry
    assert entry.unique_id == "tmt100_device_battery"


async def test_create_doorbell_hardwired(hass: HomeAssistant) -> None:
    """Test creation of a doorbell that is hardwired without a battery."""
    doorbell_one = await _mock_doorbell_from_fixture(
        hass, "get_doorbell.nobattery.json"
    )
    await _create_august_with_devices(hass, [doorbell_one])

    sensor_tmt100_name_battery = hass.states.get("sensor.tmt100_name_battery")
    assert sensor_tmt100_name_battery is None


async def test_create_lock_with_linked_keypad(hass: HomeAssistant) -> None:
    """Test creation of a lock with a linked keypad that both have a battery."""
    lock_one = await _mock_lock_from_fixture(hass, "get_lock.doorsense_init.json")
    await _create_august_with_devices(hass, [lock_one])
    entity_registry = er.async_get(hass)

    sensor_a6697750d607098bae8d6baa11ef8063_name_battery = hass.states.get(
        "sensor.a6697750d607098bae8d6baa11ef8063_name_battery"
    )
    assert sensor_a6697750d607098bae8d6baa11ef8063_name_battery.state == "88"
    assert (
        sensor_a6697750d607098bae8d6baa11ef8063_name_battery.attributes[
            "unit_of_measurement"
        ]
        == PERCENTAGE
    )
    entry = entity_registry.async_get(
        "sensor.a6697750d607098bae8d6baa11ef8063_name_battery"
    )
    assert entry
    assert entry.unique_id == "A6697750D607098BAE8D6BAA11EF8063_device_battery"

    state = hass.states.get("sensor.front_door_lock_keypad_battery")
    assert state.state == "60"
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == PERCENTAGE
    entry = entity_registry.async_get("sensor.front_door_lock_keypad_battery")
    assert entry
    assert entry.unique_id == "5bc65c24e6ef2a263e1450a8_linked_keypad_battery"


async def test_create_lock_with_low_battery_linked_keypad(hass: HomeAssistant) -> None:
    """Test creation of a lock with a linked keypad that both have a battery."""
    lock_one = await _mock_lock_from_fixture(hass, "get_lock.low_keypad_battery.json")
    await _create_august_with_devices(hass, [lock_one])
    entity_registry = er.async_get(hass)

    sensor_a6697750d607098bae8d6baa11ef8063_name_battery = hass.states.get(
        "sensor.a6697750d607098bae8d6baa11ef8063_name_battery"
    )
    assert sensor_a6697750d607098bae8d6baa11ef8063_name_battery.state == "88"
    assert (
        sensor_a6697750d607098bae8d6baa11ef8063_name_battery.attributes[
            "unit_of_measurement"
        ]
        == PERCENTAGE
    )
    entry = entity_registry.async_get(
        "sensor.a6697750d607098bae8d6baa11ef8063_name_battery"
    )
    assert entry
    assert entry.unique_id == "A6697750D607098BAE8D6BAA11EF8063_device_battery"

    state = hass.states.get("sensor.front_door_lock_keypad_battery")
    assert state.state == "10"
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == PERCENTAGE
    entry = entity_registry.async_get("sensor.front_door_lock_keypad_battery")
    assert entry
    assert entry.unique_id == "5bc65c24e6ef2a263e1450a8_linked_keypad_battery"

    # No activity means it will be unavailable until someone unlocks/locks it
    lock_operator_sensor = entity_registry.async_get(
        "sensor.a6697750d607098bae8d6baa11ef8063_name_operator"
    )
    assert (
        lock_operator_sensor.unique_id
        == "A6697750D607098BAE8D6BAA11EF8063_lock_operator"
    )
    assert (
        hass.states.get("sensor.a6697750d607098bae8d6baa11ef8063_name_operator").state
        == STATE_UNKNOWN
    )


async def test_lock_operator_bluetooth(hass: HomeAssistant) -> None:
    """Test operation of a lock with doorsense and bridge."""
    lock_one = await _mock_doorsense_enabled_august_lock_detail(hass)

    activities = await _mock_activities_from_fixture(
        hass, "get_activity.lock_from_bluetooth.json"
    )
    await _create_august_with_devices(hass, [lock_one], activities=activities)

    entity_registry = er.async_get(hass)
    lock_operator_sensor = entity_registry.async_get(
        "sensor.online_with_doorsense_name_operator"
    )
    assert lock_operator_sensor

    state = hass.states.get("sensor.online_with_doorsense_name_operator")
    assert state.state == "Your favorite elven princess"
    assert state.attributes["manual"] is False
    assert state.attributes["tag"] is False
    assert state.attributes["remote"] is False
    assert state.attributes["keypad"] is False
    assert state.attributes["autorelock"] is False
    assert state.attributes["method"] == "mobile"


async def test_lock_operator_keypad(hass: HomeAssistant) -> None:
    """Test operation of a lock with doorsense and bridge."""
    lock_one = await _mock_doorsense_enabled_august_lock_detail(hass)

    activities = await _mock_activities_from_fixture(
        hass, "get_activity.lock_from_keypad.json"
    )
    await _create_august_with_devices(hass, [lock_one], activities=activities)

    entity_registry = er.async_get(hass)
    lock_operator_sensor = entity_registry.async_get(
        "sensor.online_with_doorsense_name_operator"
    )
    assert lock_operator_sensor

    state = hass.states.get("sensor.online_with_doorsense_name_operator")
    assert state.state == "Your favorite elven princess"
    assert state.attributes["manual"] is False
    assert state.attributes["tag"] is False
    assert state.attributes["remote"] is False
    assert state.attributes["keypad"] is True
    assert state.attributes["autorelock"] is False
    assert state.attributes["method"] == "keypad"


async def test_lock_operator_remote(hass: HomeAssistant) -> None:
    """Test operation of a lock with doorsense and bridge."""
    lock_one = await _mock_doorsense_enabled_august_lock_detail(hass)

    activities = await _mock_activities_from_fixture(hass, "get_activity.lock.json")
    await _create_august_with_devices(hass, [lock_one], activities=activities)

    entity_registry = er.async_get(hass)
    lock_operator_sensor = entity_registry.async_get(
        "sensor.online_with_doorsense_name_operator"
    )
    assert lock_operator_sensor

    state = hass.states.get("sensor.online_with_doorsense_name_operator")
    assert state.state == "Your favorite elven princess"
    assert state.attributes["manual"] is False
    assert state.attributes["tag"] is False
    assert state.attributes["remote"] is True
    assert state.attributes["keypad"] is False
    assert state.attributes["autorelock"] is False
    assert state.attributes["method"] == "remote"


async def test_lock_operator_manual(hass: HomeAssistant) -> None:
    """Test operation of a lock with doorsense and bridge."""
    lock_one = await _mock_doorsense_enabled_august_lock_detail(hass)

    activities = await _mock_activities_from_fixture(
        hass, "get_activity.lock_from_manual.json"
    )
    await _create_august_with_devices(hass, [lock_one], activities=activities)

    entity_registry = er.async_get(hass)
    lock_operator_sensor = entity_registry.async_get(
        "sensor.online_with_doorsense_name_operator"
    )
    assert lock_operator_sensor
    state = hass.states.get("sensor.online_with_doorsense_name_operator")
    assert state.state == "Your favorite elven princess"
    assert state.attributes["manual"] is True
    assert state.attributes["tag"] is False
    assert state.attributes["remote"] is False
    assert state.attributes["keypad"] is False
    assert state.attributes["autorelock"] is False
    assert state.attributes["method"] == "manual"


async def test_lock_operator_autorelock(hass: HomeAssistant) -> None:
    """Test operation of a lock with doorsense and bridge."""
    lock_one = await _mock_doorsense_enabled_august_lock_detail(hass)

    activities = await _mock_activities_from_fixture(
        hass, "get_activity.lock_from_autorelock.json"
    )
    await _create_august_with_devices(hass, [lock_one], activities=activities)

    entity_registry = er.async_get(hass)
    lock_operator_sensor = entity_registry.async_get(
        "sensor.online_with_doorsense_name_operator"
    )
    assert lock_operator_sensor

    state = hass.states.get("sensor.online_with_doorsense_name_operator")
    assert state.state == "Auto Relock"
    assert state.attributes["manual"] is False
    assert state.attributes["tag"] is False
    assert state.attributes["remote"] is False
    assert state.attributes["keypad"] is False
    assert state.attributes["autorelock"] is True
    assert state.attributes["method"] == "autorelock"


async def test_unlock_operator_manual(hass: HomeAssistant) -> None:
    """Test operation of a lock manually."""
    lock_one = await _mock_doorsense_enabled_august_lock_detail(hass)

    activities = await _mock_activities_from_fixture(
        hass, "get_activity.unlock_from_manual.json"
    )
    await _create_august_with_devices(hass, [lock_one], activities=activities)

    entity_registry = er.async_get(hass)
    lock_operator_sensor = entity_registry.async_get(
        "sensor.online_with_doorsense_name_operator"
    )
    assert lock_operator_sensor

    state = hass.states.get("sensor.online_with_doorsense_name_operator")
    assert state.state == "Your favorite elven princess"
    assert state.attributes["manual"] is True
    assert state.attributes["tag"] is False
    assert state.attributes["remote"] is False
    assert state.attributes["keypad"] is False
    assert state.attributes["autorelock"] is False
    assert state.attributes["method"] == "manual"


async def test_unlock_operator_tag(hass: HomeAssistant) -> None:
    """Test operation of a lock with a tag."""
    lock_one = await _mock_doorsense_enabled_august_lock_detail(hass)

    activities = await _mock_activities_from_fixture(
        hass, "get_activity.unlock_from_tag.json"
    )
    await _create_august_with_devices(hass, [lock_one], activities=activities)

    entity_registry = er.async_get(hass)
    lock_operator_sensor = entity_registry.async_get(
        "sensor.online_with_doorsense_name_operator"
    )
    assert lock_operator_sensor

    state = hass.states.get("sensor.online_with_doorsense_name_operator")
    assert state.state == "Your favorite elven princess"
    assert state.attributes["manual"] is False
    assert state.attributes["tag"] is True
    assert state.attributes["remote"] is False
    assert state.attributes["keypad"] is False
    assert state.attributes["autorelock"] is False
    assert state.attributes["method"] == "tag"


async def test_restored_state(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Test restored state."""

    entity_id = "sensor.online_with_doorsense_name_operator"
    lock_one = await _mock_doorsense_enabled_august_lock_detail(hass)

    fake_state = ha.State(
        entity_id,
        state="Tag Unlock",
        attributes={
            "method": "tag",
            "manual": False,
            "remote": False,
            "keypad": False,
            "tag": True,
            "autorelock": False,
            ATTR_ENTITY_PICTURE: "image.png",
        },
    )

    # Home assistant is not running yet
    hass.state = CoreState.not_running
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                fake_state,
                {"native_value": "Tag Unlock", "native_unit_of_measurement": None},
            )
        ],
    )

    august_entry = await _create_august_with_devices(hass, [lock_one])
    august_entry.add_to_hass(hass)

    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "Tag Unlock"
    assert state.attributes["method"] == "tag"
    assert state.attributes[ATTR_ENTITY_PICTURE] == "image.png"
