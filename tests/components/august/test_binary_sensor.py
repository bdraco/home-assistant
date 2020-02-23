"""The binary_sensor tests for the august platform."""

import pytest

from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_LOCK,
    SERVICE_UNLOCK,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)

from tests.components.august.mocks import (
    _create_august_with_devices,
    _mock_doorbell_from_fixture,
    _mock_lock_from_fixture,
)


@pytest.mark.skip(
    reason="The lock and doorsense can get out of sync due to update intervals, this is an existing bug which will be fixed with dispatcher events to tell all linked devices to update."
)
async def test_doorsense(hass):
    """Test creation of a lock with doorsense and bridge."""
    lock_one = await _mock_lock_from_fixture(
        hass, "get_lock.online_with_doorsense.json"
    )
    lock_details = [lock_one]
    await _create_august_with_devices(hass, lock_details=lock_details)

    binary_sensor_abc_name = hass.states.get("binary_sensor.abc_name_open")
    assert binary_sensor_abc_name.state == STATE_ON

    data = {}
    data[ATTR_ENTITY_ID] = "lock.abc_name"
    assert await hass.services.async_call(
        LOCK_DOMAIN, SERVICE_UNLOCK, data, blocking=True
    )

    binary_sensor_abc_name = hass.states.get("binary_sensor.abc_name_open")
    assert binary_sensor_abc_name.state == STATE_ON

    assert await hass.services.async_call(
        LOCK_DOMAIN, SERVICE_LOCK, data, blocking=True
    )

    binary_sensor_abc_name = hass.states.get("binary_sensor.abc_name_open")
    assert binary_sensor_abc_name.state == STATE_OFF


async def test_create_doorbell(hass):
    """Test creation of a doorbell."""
    doorbell_one = await _mock_doorbell_from_fixture(hass, "get_doorbell.json")
    doorbell_details = [doorbell_one]
    await _create_august_with_devices(hass, doorbell_details=doorbell_details)

    binary_sensor_k98gidt45gul_name_motion = hass.states.get(
        "binary_sensor.k98gidt45gul_name_motion"
    )
    assert binary_sensor_k98gidt45gul_name_motion.state == STATE_OFF
    binary_sensor_k98gidt45gul_name_online = hass.states.get(
        "binary_sensor.k98gidt45gul_name_online"
    )
    assert binary_sensor_k98gidt45gul_name_online.state == STATE_ON
    binary_sensor_k98gidt45gul_name_ding = hass.states.get(
        "binary_sensor.k98gidt45gul_name_ding"
    )
    assert binary_sensor_k98gidt45gul_name_ding.state == STATE_OFF


async def test_create_doorbell_offline(hass):
    """Test creation of a doorbell that is offline."""
    doorbell_one = await _mock_doorbell_from_fixture(hass, "get_doorbell.offline.json")
    doorbell_details = [doorbell_one]
    await _create_august_with_devices(hass, doorbell_details=doorbell_details)

    binary_sensor_tmt100_name_motion = hass.states.get(
        "binary_sensor.tmt100_name_motion"
    )
    assert binary_sensor_tmt100_name_motion.state == STATE_UNAVAILABLE
    binary_sensor_tmt100_name_online = hass.states.get(
        "binary_sensor.tmt100_name_online"
    )
    assert binary_sensor_tmt100_name_online.state == STATE_OFF
    binary_sensor_tmt100_name_ding = hass.states.get("binary_sensor.tmt100_name_ding")
    assert binary_sensor_tmt100_name_ding.state == STATE_UNAVAILABLE
