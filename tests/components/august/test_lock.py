"""The lock tests for the august platform."""

from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_LOCK,
    SERVICE_UNLOCK,
    STATE_LOCKED,
    STATE_UNKNOWN,
    STATE_UNLOCKED,
)

from tests.components.august.mocks import (
    _create_august_with_devices,
    _mock_lock_from_fixture,
)


async def test_one_lock_operation(hass):
    """Test creation of a lock with doorsense and bridge."""
    lock_one = await _mock_lock_from_fixture(
        hass, "get_lock.online_with_doorsense.json"
    )
    lock_details = [lock_one]
    await _create_august_with_devices(hass, lock_details)

    lock_abc_name = hass.states.get("lock.abc_name")

    assert lock_abc_name.state == STATE_LOCKED

    assert lock_abc_name.attributes.get("battery_level") == 92
    assert lock_abc_name.attributes.get("friendly_name") == "ABC Name"

    data = {}
    data[ATTR_ENTITY_ID] = "lock.abc_name"
    assert await hass.services.async_call(
        LOCK_DOMAIN, SERVICE_UNLOCK, data, blocking=True
    )

    lock_abc_name = hass.states.get("lock.abc_name")
    assert lock_abc_name.state == STATE_UNLOCKED

    assert lock_abc_name.attributes.get("battery_level") == 92
    assert lock_abc_name.attributes.get("friendly_name") == "ABC Name"

    assert await hass.services.async_call(
        LOCK_DOMAIN, SERVICE_LOCK, data, blocking=True
    )

    lock_abc_name = hass.states.get("lock.abc_name")
    assert lock_abc_name.state == STATE_LOCKED


async def test_one_lock_unknown_state(hass):
    """Test creation of a lock with doorsense and bridge."""
    lock_one = await _mock_lock_from_fixture(
        hass, "get_lock.online.unknown_state.json",
    )
    lock_details = [lock_one]
    await _create_august_with_devices(hass, lock_details)

    import pprint
    from homeassistant.helpers.json import JSONEncoder
    import json

    pprint.pprint(json.dumps(hass.states.async_all(), cls=JSONEncoder))

    lock_brokenid_name = hass.states.get("lock.brokenid_name")

    assert lock_brokenid_name.state == STATE_UNKNOWN
