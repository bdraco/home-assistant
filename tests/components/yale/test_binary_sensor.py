"""The binary_sensor tests for the yale platform."""

import datetime
from unittest.mock import patch

from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_LOCK,
    SERVICE_UNLOCK,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import homeassistant.util.dt as dt_util

from .mocks import (
    _create_yale_with_devices,
    _mock_activities_from_fixture,
    _mock_doorbell_from_fixture,
    _mock_doorsense_enabled_yale_lock_detail,
    _mock_lock_from_fixture,
)

from tests.common import async_fire_time_changed


async def test_doorsense(hass: HomeAssistant) -> None:
    """Test creation of a lock with doorsense and bridge."""
    lock_one = await _mock_lock_from_fixture(
        hass, "get_lock.online_with_doorsense.json"
    )
    await _create_yale_with_devices(hass, [lock_one])

    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_ON

    data = {ATTR_ENTITY_ID: "lock.online_with_doorsense_name"}
    await hass.services.async_call(LOCK_DOMAIN, SERVICE_UNLOCK, data, blocking=True)
    await hass.async_block_till_done()

    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_ON

    await hass.services.async_call(LOCK_DOMAIN, SERVICE_LOCK, data, blocking=True)
    await hass.async_block_till_done()

    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_OFF


async def test_lock_bridge_offline(hass: HomeAssistant) -> None:
    """Test creation of a lock with doorsense and bridge that goes offline."""
    lock_one = await _mock_lock_from_fixture(
        hass, "get_lock.online_with_doorsense.json"
    )
    activities = await _mock_activities_from_fixture(
        hass, "get_activity.bridge_offline.json"
    )
    await _create_yale_with_devices(hass, [lock_one], activities=activities)

    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_UNAVAILABLE


async def test_create_doorbell(hass: HomeAssistant) -> None:
    """Test creation of a doorbell."""
    doorbell_one = await _mock_doorbell_from_fixture(hass, "get_doorbell.json")
    await _create_yale_with_devices(hass, [doorbell_one])

    binary_sensor_k98gidt45gul_name_motion = hass.states.get(
        "binary_sensor.k98gidt45gul_name_motion"
    )
    assert binary_sensor_k98gidt45gul_name_motion.state == STATE_OFF
    binary_sensor_k98gidt45gul_name_image_capture = hass.states.get(
        "binary_sensor.k98gidt45gul_name_image_capture"
    )
    assert binary_sensor_k98gidt45gul_name_image_capture.state == STATE_OFF
    binary_sensor_k98gidt45gul_name_online = hass.states.get(
        "binary_sensor.k98gidt45gul_name_connectivity"
    )
    assert binary_sensor_k98gidt45gul_name_online.state == STATE_ON
    binary_sensor_k98gidt45gul_name_ding = hass.states.get(
        "binary_sensor.k98gidt45gul_name_doorbell_ding"
    )
    assert binary_sensor_k98gidt45gul_name_ding.state == STATE_OFF
    binary_sensor_k98gidt45gul_name_motion = hass.states.get(
        "binary_sensor.k98gidt45gul_name_motion"
    )
    assert binary_sensor_k98gidt45gul_name_motion.state == STATE_OFF
    binary_sensor_k98gidt45gul_name_image_capture = hass.states.get(
        "binary_sensor.k98gidt45gul_name_image_capture"
    )
    assert binary_sensor_k98gidt45gul_name_image_capture.state == STATE_OFF


async def test_create_doorbell_offline(hass: HomeAssistant) -> None:
    """Test creation of a doorbell that is offline."""
    doorbell_one = await _mock_doorbell_from_fixture(hass, "get_doorbell.offline.json")
    await _create_yale_with_devices(hass, [doorbell_one])

    binary_sensor_tmt100_name_motion = hass.states.get(
        "binary_sensor.tmt100_name_motion"
    )
    assert binary_sensor_tmt100_name_motion.state == STATE_UNAVAILABLE
    binary_sensor_tmt100_name_online = hass.states.get(
        "binary_sensor.tmt100_name_connectivity"
    )
    assert binary_sensor_tmt100_name_online.state == STATE_OFF
    binary_sensor_tmt100_name_ding = hass.states.get(
        "binary_sensor.tmt100_name_doorbell_ding"
    )
    assert binary_sensor_tmt100_name_ding.state == STATE_UNAVAILABLE


async def test_create_doorbell_with_motion(hass: HomeAssistant) -> None:
    """Test creation of a doorbell."""
    doorbell_one = await _mock_doorbell_from_fixture(hass, "get_doorbell.json")
    activities = await _mock_activities_from_fixture(
        hass, "get_activity.doorbell_motion.json"
    )
    await _create_yale_with_devices(hass, [doorbell_one], activities=activities)

    binary_sensor_k98gidt45gul_name_motion = hass.states.get(
        "binary_sensor.k98gidt45gul_name_motion"
    )
    assert binary_sensor_k98gidt45gul_name_motion.state == STATE_ON
    binary_sensor_k98gidt45gul_name_online = hass.states.get(
        "binary_sensor.k98gidt45gul_name_connectivity"
    )
    assert binary_sensor_k98gidt45gul_name_online.state == STATE_ON
    binary_sensor_k98gidt45gul_name_ding = hass.states.get(
        "binary_sensor.k98gidt45gul_name_doorbell_ding"
    )
    assert binary_sensor_k98gidt45gul_name_ding.state == STATE_OFF
    new_time = dt_util.utcnow() + datetime.timedelta(seconds=40)
    native_time = datetime.datetime.now() + datetime.timedelta(seconds=40)
    with patch(
        "homeassistant.components.yale.util._native_datetime",
        return_value=native_time,
    ):
        async_fire_time_changed(hass, new_time)
        await hass.async_block_till_done()
    binary_sensor_k98gidt45gul_name_motion = hass.states.get(
        "binary_sensor.k98gidt45gul_name_motion"
    )
    assert binary_sensor_k98gidt45gul_name_motion.state == STATE_OFF


async def test_doorbell_update_via_socketio(hass: HomeAssistant) -> None:
    """Test creation of a doorbell that can be updated via socketio."""
    doorbell_one = await _mock_doorbell_from_fixture(hass, "get_doorbell.json")

    _, socketio = await _create_yale_with_devices(hass, [doorbell_one])
    assert doorbell_one.pubsub_channel == "7c7a6672-59c8-3333-ffff-dcd98705cccc"

    binary_sensor_k98gidt45gul_name_motion = hass.states.get(
        "binary_sensor.k98gidt45gul_name_motion"
    )
    assert binary_sensor_k98gidt45gul_name_motion.state == STATE_OFF
    binary_sensor_k98gidt45gul_name_ding = hass.states.get(
        "binary_sensor.k98gidt45gul_name_doorbell_ding"
    )
    assert binary_sensor_k98gidt45gul_name_ding.state == STATE_OFF

    listener = list(socketio._listeners)[0]
    listener(
        doorbell_one.device_id,
        dt_util.utcnow(),
        {
            "status": "imagecapture",
            "data": {
                "result": {
                    "created_at": "2021-03-16T01:07:08.817Z",
                    "secure_url": (
                        "https://dyu7azbnaoi74.cloudfront.net/zip/images/zip.jpeg"
                    ),
                },
            },
        },
    )

    await hass.async_block_till_done()

    binary_sensor_k98gidt45gul_name_image_capture = hass.states.get(
        "binary_sensor.k98gidt45gul_name_image_capture"
    )
    assert binary_sensor_k98gidt45gul_name_image_capture.state == STATE_ON

    listener(
        doorbell_one.device_id,
        dt_util.utcnow(),
        {
            "status": "doorbell_motion_detected",
            "data": {
                "event": "doorbell_motion_detected",
                "image": {
                    "height": 640,
                    "width": 480,
                    "format": "jpg",
                    "created_at": "2021-03-16T02:36:26.886Z",
                    "bytes": 14061,
                    "secure_url": (
                        "https://dyu7azbnaoi74.cloudfront.net/images/1f8.jpeg"
                    ),
                    "url": "https://dyu7azbnaoi74.cloudfront.net/images/1f8.jpeg",
                    "etag": "09e839331c4ea59eef28081f2caa0e90",
                },
                "doorbellName": "Front Door",
                "callID": None,
                "origin": "mars-api",
                "mutableContent": True,
            },
        },
    )

    await hass.async_block_till_done()

    binary_sensor_k98gidt45gul_name_motion = hass.states.get(
        "binary_sensor.k98gidt45gul_name_motion"
    )
    assert binary_sensor_k98gidt45gul_name_motion.state == STATE_ON

    binary_sensor_k98gidt45gul_name_ding = hass.states.get(
        "binary_sensor.k98gidt45gul_name_doorbell_ding"
    )
    assert binary_sensor_k98gidt45gul_name_ding.state == STATE_OFF

    new_time = dt_util.utcnow() + datetime.timedelta(seconds=40)
    native_time = datetime.datetime.now() + datetime.timedelta(seconds=40)
    with patch(
        "homeassistant.components.yale.util._native_datetime",
        return_value=native_time,
    ):
        async_fire_time_changed(hass, new_time)
        await hass.async_block_till_done()

    binary_sensor_k98gidt45gul_name_image_capture = hass.states.get(
        "binary_sensor.k98gidt45gul_name_image_capture"
    )
    assert binary_sensor_k98gidt45gul_name_image_capture.state == STATE_OFF

    listener(
        doorbell_one.device_id,
        dt_util.utcnow(),
        {
            "status": "buttonpush",
        },
    )

    await hass.async_block_till_done()

    binary_sensor_k98gidt45gul_name_ding = hass.states.get(
        "binary_sensor.k98gidt45gul_name_doorbell_ding"
    )
    assert binary_sensor_k98gidt45gul_name_ding.state == STATE_ON
    new_time = dt_util.utcnow() + datetime.timedelta(seconds=40)
    native_time = datetime.datetime.now() + datetime.timedelta(seconds=40)
    with patch(
        "homeassistant.components.yale.util._native_datetime",
        return_value=native_time,
    ):
        async_fire_time_changed(hass, new_time)
        await hass.async_block_till_done()

    binary_sensor_k98gidt45gul_name_ding = hass.states.get(
        "binary_sensor.k98gidt45gul_name_doorbell_ding"
    )
    assert binary_sensor_k98gidt45gul_name_ding.state == STATE_OFF


async def test_doorbell_device_registry(
    hass: HomeAssistant, device_registry: dr.DeviceRegistry
) -> None:
    """Test creation of a lock with doorsense and bridge ands up in the registry."""
    doorbell_one = await _mock_doorbell_from_fixture(hass, "get_doorbell.offline.json")
    await _create_yale_with_devices(hass, [doorbell_one])

    reg_device = device_registry.async_get_device(identifiers={("yale", "tmt100")})
    assert reg_device.model == "hydra1"
    assert reg_device.name == "tmt100 Name"
    assert reg_device.manufacturer == "Yale Home Inc."
    assert reg_device.sw_version == "3.1.0-HYDRC75+201909251139"


async def test_door_sense_update_via_socketio(hass: HomeAssistant) -> None:
    """Test creation of a lock with doorsense and bridge."""
    lock_one = await _mock_doorsense_enabled_yale_lock_detail(hass)
    assert lock_one.pubsub_channel == "pubsub"

    activities = await _mock_activities_from_fixture(hass, "get_activity.lock.json")
    config_entry, socketio = await _create_yale_with_devices(
        hass, [lock_one], activities=activities
    )

    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_ON

    listener = list(socketio._listeners)[0]
    listener(
        lock_one.device_id,
        dt_util.utcnow(),
        {"status": "kAugLockState_Unlocking", "doorState": "closed"},
    )

    await hass.async_block_till_done()
    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_OFF

    listener(
        lock_one.device_id,
        dt_util.utcnow(),
        {"status": "kAugLockState_Locking", "doorState": "open"},
    )

    await hass.async_block_till_done()
    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_ON

    async_fire_time_changed(hass, dt_util.utcnow() + datetime.timedelta(seconds=30))
    await hass.async_block_till_done()
    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_ON

    socketio.connected = True
    async_fire_time_changed(hass, dt_util.utcnow() + datetime.timedelta(seconds=30))
    await hass.async_block_till_done()
    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_ON

    # Ensure socketio status is always preserved
    async_fire_time_changed(hass, dt_util.utcnow() + datetime.timedelta(hours=2))
    await hass.async_block_till_done()
    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_ON

    listener(
        lock_one.device_id,
        dt_util.utcnow(),
        {"status": "kAugLockState_Unlocking", "doorState": "open"},
    )

    await hass.async_block_till_done()
    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_ON

    async_fire_time_changed(hass, dt_util.utcnow() + datetime.timedelta(hours=4))
    await hass.async_block_till_done()
    binary_sensor_online_with_doorsense_name = hass.states.get(
        "binary_sensor.online_with_doorsense_name_door"
    )
    assert binary_sensor_online_with_doorsense_name.state == STATE_ON

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_create_lock_with_doorbell(hass: HomeAssistant) -> None:
    """Test creation of a lock with a doorbell."""
    lock_one = await _mock_lock_from_fixture(hass, "lock_with_doorbell.online.json")
    await _create_yale_with_devices(hass, [lock_one])

    ding_sensor = hass.states.get(
        "binary_sensor.a6697750d607098bae8d6baa11ef8063_name_doorbell_ding"
    )
    assert ding_sensor.state == STATE_OFF
