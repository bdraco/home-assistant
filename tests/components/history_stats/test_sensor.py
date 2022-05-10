"""The test for the History Statistics sensor platform."""
# pylint: disable=protected-access
from datetime import timedelta
import unittest
from unittest.mock import patch

from freezegun import freeze_time
import pytest

from homeassistant import config as hass_config
from homeassistant.components.history_stats import DOMAIN
from homeassistant.const import SERVICE_RELOAD, STATE_UNAVAILABLE, STATE_UNKNOWN
import homeassistant.core as ha
from homeassistant.helpers.entity_component import async_update_entity
from homeassistant.setup import async_setup_component, setup_component
import homeassistant.util.dt as dt_util

from tests.common import (
    async_fire_time_changed,
    get_fixture_path,
    get_test_home_assistant,
    init_recorder_component,
)


class TestHistoryStatsSensor(unittest.TestCase):
    """Test the History Statistics sensor."""

    def setUp(self):
        """Set up things to be run when tests are started."""
        self.hass = get_test_home_assistant()
        self.addCleanup(self.hass.stop)

    def test_setup(self):
        """Test the history statistics sensor setup."""
        self.init_recorder()
        config = {
            "sensor": {
                "platform": "history_stats",
                "entity_id": "binary_sensor.test_id",
                "state": "on",
                "start": "{{ now().replace(hour=0)"
                ".replace(minute=0).replace(second=0) }}",
                "duration": "02:00",
                "name": "Test",
            },
        }

        assert setup_component(self.hass, "sensor", config)
        self.hass.block_till_done()

        state = self.hass.states.get("sensor.test")
        assert state.state == STATE_UNKNOWN

    def test_setup_multiple_states(self):
        """Test the history statistics sensor setup for multiple states."""
        self.init_recorder()
        config = {
            "sensor": {
                "platform": "history_stats",
                "entity_id": "binary_sensor.test_id",
                "state": ["on", "true"],
                "start": "{{ now().replace(hour=0)"
                ".replace(minute=0).replace(second=0) }}",
                "duration": "02:00",
                "name": "Test",
            },
        }

        assert setup_component(self.hass, "sensor", config)
        self.hass.block_till_done()

        state = self.hass.states.get("sensor.test")
        assert state.state == STATE_UNKNOWN

    def test_wrong_duration(self):
        """Test when duration value is not a timedelta."""
        self.init_recorder()
        config = {
            "sensor": {
                "platform": "history_stats",
                "entity_id": "binary_sensor.test_id",
                "name": "Test",
                "state": "on",
                "start": "{{ now() }}",
                "duration": "TEST",
            },
        }

        setup_component(self.hass, "sensor", config)
        assert self.hass.states.get("sensor.test") is None
        with pytest.raises(TypeError):
            setup_component(self.hass, "sensor", config)()

    def test_not_enough_arguments(self):
        """Test config when not enough arguments provided."""
        self.init_recorder()
        config = {
            "sensor": {
                "platform": "history_stats",
                "entity_id": "binary_sensor.test_id",
                "name": "Test",
                "state": "on",
                "start": "{{ now() }}",
            },
        }

        setup_component(self.hass, "sensor", config)
        assert self.hass.states.get("sensor.test") is None
        with pytest.raises(TypeError):
            setup_component(self.hass, "sensor", config)()

    def test_too_many_arguments(self):
        """Test config when too many arguments provided."""
        self.init_recorder()
        config = {
            "sensor": {
                "platform": "history_stats",
                "entity_id": "binary_sensor.test_id",
                "name": "Test",
                "state": "on",
                "start": "{{ as_timestamp(now()) - 3600 }}",
                "end": "{{ now() }}",
                "duration": "01:00",
            },
        }

        setup_component(self.hass, "sensor", config)
        assert self.hass.states.get("sensor.test") is None
        with pytest.raises(TypeError):
            setup_component(self.hass, "sensor", config)()

    def init_recorder(self):
        """Initialize the recorder."""
        init_recorder_component(self.hass)
        self.hass.start()


async def test_invalid_date_for_start(hass, recorder_mock):
    """Verify with an invalid date for start."""
    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": {
                "platform": "history_stats",
                "entity_id": "binary_sensor.test_id",
                "name": "test",
                "state": "on",
                "start": "{{ INVALID }}",
                "duration": "01:00",
            },
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test").state == STATE_UNKNOWN
    next_update_time = dt_util.utcnow() + timedelta(minutes=1)
    with freeze_time(next_update_time):
        async_fire_time_changed(hass, next_update_time)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.test").state == STATE_UNAVAILABLE


async def test_invalid_date_for_end(hass, recorder_mock):
    """Verify with an invalid date for end."""
    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": {
                "platform": "history_stats",
                "entity_id": "binary_sensor.test_id",
                "name": "test",
                "state": "on",
                "end": "{{ INVALID }}",
                "duration": "01:00",
            },
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test").state == STATE_UNKNOWN
    next_update_time = dt_util.utcnow() + timedelta(minutes=1)
    with freeze_time(next_update_time):
        async_fire_time_changed(hass, next_update_time)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.test").state == STATE_UNAVAILABLE


async def test_invalid_entity_in_template(hass, recorder_mock):
    """Verify with an invalid entity in the template."""
    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": {
                "platform": "history_stats",
                "entity_id": "binary_sensor.test_id",
                "name": "test",
                "state": "on",
                "end": "{{ states('binary_sensor.invalid').attributes.time }}",
                "duration": "01:00",
            },
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test").state == STATE_UNKNOWN
    next_update_time = dt_util.utcnow() + timedelta(minutes=1)
    with freeze_time(next_update_time):
        async_fire_time_changed(hass, next_update_time)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.test").state == STATE_UNAVAILABLE


async def test_invalid_entity_returning_none_in_template(hass, recorder_mock):
    """Verify with an invalid entity returning none in the template."""
    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": {
                "platform": "history_stats",
                "entity_id": "binary_sensor.test_id",
                "name": "test",
                "state": "on",
                "end": "{{ states.binary_sensor.invalid.attributes.time }}",
                "duration": "01:00",
            },
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test").state == STATE_UNKNOWN
    next_update_time = dt_util.utcnow() + timedelta(minutes=1)
    with freeze_time(next_update_time):
        async_fire_time_changed(hass, next_update_time)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.test").state == STATE_UNAVAILABLE


async def test_reload(hass, recorder_mock):
    """Verify we can reload history_stats sensors."""
    hass.state = ha.CoreState.not_running
    hass.states.async_set("binary_sensor.test_id", "on")

    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": {
                "platform": "history_stats",
                "entity_id": "binary_sensor.test_id",
                "name": "test",
                "state": "on",
                "start": "{{ as_timestamp(now()) - 3600 }}",
                "duration": "01:00",
            },
        },
    )
    await hass.async_block_till_done()
    await hass.async_start()
    await hass.async_block_till_done()

    assert len(hass.states.async_all()) == 2

    assert hass.states.get("sensor.test")

    yaml_path = get_fixture_path("configuration.yaml", "history_stats")
    with patch.object(hass_config, "YAML_CONFIG_FILE", yaml_path):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RELOAD,
            {},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert len(hass.states.async_all()) == 2

    assert hass.states.get("sensor.test") is None
    assert hass.states.get("sensor.second_test")


async def test_measure_multiple(hass, recorder_mock):
    """Test the history statistics sensor measure for multiple ."""
    start_time = dt_util.utcnow() - timedelta(minutes=60)
    t0 = start_time + timedelta(minutes=20)
    t1 = t0 + timedelta(minutes=10)
    t2 = t1 + timedelta(minutes=10)

    # Start     t0        t1        t2        End
    # |--20min--|--20min--|--10min--|--10min--|
    # |---------|--orange-|-default-|---blue--|

    def _fake_states(*args, **kwargs):
        return {
            "input_select.test_id": [
                # Because we use include_start_time_state we need to mock
                # value at start
                ha.State("input_select.test_id", "", last_changed=start_time),
                ha.State("input_select.test_id", "orange", last_changed=t0),
                ha.State("input_select.test_id", "default", last_changed=t1),
                ha.State("input_select.test_id", "blue", last_changed=t2),
            ]
        }

    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": [
                {
                    "platform": "history_stats",
                    "entity_id": "input_select.test_id",
                    "name": "sensor1",
                    "state": ["orange", "blue"],
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "unknown.test_id",
                    "name": "sensor2",
                    "state": ["orange", "blue"],
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "input_select.test_id",
                    "name": "sensor3",
                    "state": ["orange", "blue"],
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "count",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "input_select.test_id",
                    "name": "sensor4",
                    "state": ["orange", "blue"],
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "ratio",
                },
            ]
        },
    )
    await hass.async_block_till_done()

    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ):
        for i in range(1, 5):
            await async_update_entity(hass, f"sensor.sensor{i}")
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "0.5"
    assert hass.states.get("sensor.sensor2").state == STATE_UNKNOWN
    assert hass.states.get("sensor.sensor3").state == "2"
    assert hass.states.get("sensor.sensor4").state == "50.0"


async def test_measure(hass, recorder_mock):
    """Test the history statistics sensor measure."""
    start_time = dt_util.utcnow() - timedelta(minutes=60)
    t0 = start_time + timedelta(minutes=20)
    t1 = t0 + timedelta(minutes=10)
    t2 = t1 + timedelta(minutes=10)

    # Start     t0        t1        t2        End
    # |--20min--|--20min--|--10min--|--10min--|
    # |---off---|---on----|---off---|---on----|

    def _fake_states(*args, **kwargs):
        return {
            "binary_sensor.test_id": [
                ha.State("binary_sensor.test_id", "on", last_changed=t0),
                ha.State("binary_sensor.test_id", "off", last_changed=t1),
                ha.State("binary_sensor.test_id", "on", last_changed=t2),
            ]
        }

    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": [
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor1",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor2",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor3",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "count",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor4",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "ratio",
                },
            ]
        },
    )
    await hass.async_block_till_done()

    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ):
        for i in range(1, 5):
            await async_update_entity(hass, f"sensor.sensor{i}")
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "0.83"
    assert hass.states.get("sensor.sensor2").state == "0.83"
    assert hass.states.get("sensor.sensor3").state == "1"
    assert hass.states.get("sensor.sensor4").state == "83.3"


async def test_async_on_entire_period(hass, recorder_mock):
    """Test the history statistics sensor measuring as on the entire period."""
    start_time = dt_util.utcnow() - timedelta(minutes=60)
    t0 = start_time + timedelta(minutes=20)
    t1 = t0 + timedelta(minutes=10)
    t2 = t1 + timedelta(minutes=10)

    # Start     t0        t1        t2        End
    # |--20min--|--20min--|--10min--|--10min--|
    # |---on----|--off----|---on----|--off----|

    def _fake_states(*args, **kwargs):
        return {
            "binary_sensor.test_on_id": [
                ha.State("binary_sensor.test_on_id", "on", last_changed=start_time),
                ha.State("binary_sensor.test_on_id", "on", last_changed=t0),
                ha.State("binary_sensor.test_on_id", "on", last_changed=t1),
                ha.State("binary_sensor.test_on_id", "on", last_changed=t2),
            ]
        }

    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": [
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_on_id",
                    "name": "on_sensor1",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_on_id",
                    "name": "on_sensor2",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_on_id",
                    "name": "on_sensor3",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "count",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_on_id",
                    "name": "on_sensor4",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "ratio",
                },
            ]
        },
    )
    await hass.async_block_till_done()

    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ):
        for i in range(1, 5):
            await async_update_entity(hass, f"sensor.on_sensor{i}")
        await hass.async_block_till_done()

    assert hass.states.get("sensor.on_sensor1").state == "1.0"
    assert hass.states.get("sensor.on_sensor2").state == "1.0"
    assert hass.states.get("sensor.on_sensor3").state == "0"
    assert hass.states.get("sensor.on_sensor4").state == "100.0"


async def test_async_off_entire_period(hass, recorder_mock):
    """Test the history statistics sensor measuring as off the entire period."""
    start_time = dt_util.utcnow() - timedelta(minutes=60)
    t0 = start_time + timedelta(minutes=20)
    t1 = t0 + timedelta(minutes=10)
    t2 = t1 + timedelta(minutes=10)

    # Start     t0        t1        t2        End
    # |--20min--|--20min--|--10min--|--10min--|
    # |---off----|--off----|---off----|--off----|

    def _fake_states(*args, **kwargs):
        return {
            "binary_sensor.test_on_id": [
                ha.State("binary_sensor.test_on_id", "off", last_changed=start_time),
                ha.State("binary_sensor.test_on_id", "off", last_changed=t0),
                ha.State("binary_sensor.test_on_id", "off", last_changed=t1),
                ha.State("binary_sensor.test_on_id", "off", last_changed=t2),
            ]
        }

    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": [
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_on_id",
                    "name": "on_sensor1",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_on_id",
                    "name": "on_sensor2",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_on_id",
                    "name": "on_sensor3",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "count",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_on_id",
                    "name": "on_sensor4",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ now() }}",
                    "type": "ratio",
                },
            ]
        },
    )
    await hass.async_block_till_done()

    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ):
        for i in range(1, 5):
            await async_update_entity(hass, f"sensor.on_sensor{i}")
        await hass.async_block_till_done()

    assert hass.states.get("sensor.on_sensor1").state == "0.0"
    assert hass.states.get("sensor.on_sensor2").state == "0.0"
    assert hass.states.get("sensor.on_sensor3").state == "0"
    assert hass.states.get("sensor.on_sensor4").state == "0.0"


async def test_async_start_from_history_and_switch_to_watching_state_changes_single(
    hass,
    recorder_mock,
):
    """Test we startup from history and switch to watching state changes."""
    hass.config.set_time_zone("UTC")
    utcnow = dt_util.utcnow()
    start_time = utcnow.replace(hour=0, minute=0, second=0, microsecond=0)

    # Start     t0        t1        t2       Startup                                       End
    # |--20min--|--20min--|--10min--|--10min--|---------30min---------|---15min--|---15min--|
    # |---on----|---on----|---on----|---on----|----------on-----------|---off----|----on----|

    def _fake_states(*args, **kwargs):
        return {
            "binary_sensor.state": [
                ha.State(
                    "binary_sensor.state",
                    "on",
                    last_changed=start_time,
                    last_updated=start_time,
                ),
            ]
        }

    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ):

        with freeze_time(start_time):
            await async_setup_component(
                hass,
                "sensor",
                {
                    "sensor": [
                        {
                            "platform": "history_stats",
                            "entity_id": "binary_sensor.state",
                            "name": "sensor1",
                            "state": "on",
                            "start": "{{ utcnow().replace(hour=0, minute=0, second=0) }}",
                            "duration": {"hours": 2},
                            "type": "time",
                        }
                    ]
                },
            )
            await hass.async_block_till_done()

            await async_update_entity(hass, "sensor.sensor1")
            await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "0.0"

    one_hour_in = start_time + timedelta(minutes=60)
    with freeze_time(one_hour_in):
        async_fire_time_changed(hass, one_hour_in)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.0"

    turn_off_time = start_time + timedelta(minutes=90)
    with freeze_time(turn_off_time):
        hass.states.async_set("binary_sensor.state", "off")
        await hass.async_block_till_done()
        async_fire_time_changed(hass, turn_off_time)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.5"

    turn_back_on_time = start_time + timedelta(minutes=105)
    with freeze_time(turn_back_on_time):
        async_fire_time_changed(hass, turn_back_on_time)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.5"

    with freeze_time(turn_back_on_time):
        hass.states.async_set("binary_sensor.state", "on")
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.5"

    end_time = start_time + timedelta(minutes=120)
    with freeze_time(end_time):
        async_fire_time_changed(hass, end_time)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.75"

    # The window has ended, it should not change again
    after_end_time = start_time + timedelta(minutes=125)
    with freeze_time(after_end_time):
        async_fire_time_changed(hass, after_end_time)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.75"


async def test_async_start_from_history_and_switch_to_watching_state_changes_single_expanding_window(
    hass,
    recorder_mock,
):
    """Test we startup from history and switch to watching state changes with an expanding end time."""
    hass.config.set_time_zone("UTC")
    utcnow = dt_util.utcnow()
    start_time = utcnow.replace(hour=0, minute=0, second=0, microsecond=0)

    # Start     t0        t1        t2       Startup                                       End
    # |--20min--|--20min--|--10min--|--10min--|---------30min---------|---15min--|---15min--|
    # |---on----|---on----|---on----|---on----|----------on-----------|---off----|----on----|

    def _fake_states(*args, **kwargs):
        return {
            "binary_sensor.state": [
                ha.State(
                    "binary_sensor.state",
                    "on",
                    last_changed=start_time,
                    last_updated=start_time,
                ),
            ]
        }

    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ):

        with freeze_time(start_time):
            await async_setup_component(
                hass,
                "sensor",
                {
                    "sensor": [
                        {
                            "platform": "history_stats",
                            "entity_id": "binary_sensor.state",
                            "name": "sensor1",
                            "state": "on",
                            "start": "{{ utcnow().replace(hour=0, minute=0, second=0) }}",
                            "end": "{{ utcnow() }}",
                            "type": "time",
                        }
                    ]
                },
            )
            await hass.async_block_till_done()

            await async_update_entity(hass, "sensor.sensor1")
            await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "0.0"

    one_hour_in = start_time + timedelta(minutes=60)
    with freeze_time(one_hour_in):
        async_fire_time_changed(hass, one_hour_in)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.0"

    turn_off_time = start_time + timedelta(minutes=90)
    with freeze_time(turn_off_time):
        hass.states.async_set("binary_sensor.state", "off")
        await hass.async_block_till_done()
        async_fire_time_changed(hass, turn_off_time)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.5"

    turn_back_on_time = start_time + timedelta(minutes=105)
    with freeze_time(turn_back_on_time):
        async_fire_time_changed(hass, turn_back_on_time)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.5"

    with freeze_time(turn_back_on_time):
        hass.states.async_set("binary_sensor.state", "on")
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.5"

    next_update_time = start_time + timedelta(minutes=107)
    with freeze_time(next_update_time):
        async_fire_time_changed(hass, next_update_time)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.53"

    end_time = start_time + timedelta(minutes=120)
    with freeze_time(end_time):
        async_fire_time_changed(hass, end_time)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.75"


async def test_async_start_from_history_and_switch_to_watching_state_changes_multiple(
    hass,
    recorder_mock,
):
    """Test we startup from history and switch to watching state changes."""
    hass.config.set_time_zone("UTC")
    utcnow = dt_util.utcnow()
    start_time = utcnow.replace(hour=0, minute=0, second=0, microsecond=0)

    # Start     t0        t1        t2       Startup                                       End
    # |--20min--|--20min--|--10min--|--10min--|---------30min---------|---15min--|---15min--|
    # |---on----|---on----|---on----|---on----|----------on-----------|---off----|----on----|

    def _fake_states(*args, **kwargs):
        return {
            "binary_sensor.state": [
                ha.State(
                    "binary_sensor.state",
                    "on",
                    last_changed=start_time,
                    last_updated=start_time,
                ),
            ]
        }

    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ):

        with freeze_time(start_time):
            await async_setup_component(
                hass,
                "sensor",
                {
                    "sensor": [
                        {
                            "platform": "history_stats",
                            "entity_id": "binary_sensor.state",
                            "name": "sensor1",
                            "state": "on",
                            "start": "{{ utcnow().replace(hour=0, minute=0, second=0) }}",
                            "duration": {"hours": 2},
                            "type": "time",
                        },
                        {
                            "platform": "history_stats",
                            "entity_id": "binary_sensor.state",
                            "name": "sensor2",
                            "state": "on",
                            "start": "{{ utcnow().replace(hour=0, minute=0, second=0) }}",
                            "duration": {"hours": 2},
                            "type": "time",
                        },
                        {
                            "platform": "history_stats",
                            "entity_id": "binary_sensor.state",
                            "name": "sensor3",
                            "state": "on",
                            "start": "{{ utcnow().replace(hour=0, minute=0, second=0) }}",
                            "duration": {"hours": 2},
                            "type": "count",
                        },
                        {
                            "platform": "history_stats",
                            "entity_id": "binary_sensor.state",
                            "name": "sensor4",
                            "state": "on",
                            "start": "{{ utcnow().replace(hour=0, minute=0, second=0) }}",
                            "duration": {"hours": 2},
                            "type": "ratio",
                        },
                    ]
                },
            )
            await hass.async_block_till_done()

            for i in range(1, 5):
                await async_update_entity(hass, f"sensor.sensor{i}")
            await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "0.0"
    assert hass.states.get("sensor.sensor2").state == "0.0"
    assert hass.states.get("sensor.sensor3").state == "0"
    assert hass.states.get("sensor.sensor4").state == "0.0"

    one_hour_in = start_time + timedelta(minutes=60)
    with freeze_time(one_hour_in):
        async_fire_time_changed(hass, one_hour_in)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.0"
    assert hass.states.get("sensor.sensor2").state == "1.0"
    assert hass.states.get("sensor.sensor3").state == "0"
    assert hass.states.get("sensor.sensor4").state == "50.0"

    turn_off_time = start_time + timedelta(minutes=90)
    with freeze_time(turn_off_time):
        hass.states.async_set("binary_sensor.state", "off")
        await hass.async_block_till_done()
        async_fire_time_changed(hass, turn_off_time)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.5"
    assert hass.states.get("sensor.sensor2").state == "1.5"
    assert hass.states.get("sensor.sensor3").state == "0"
    assert hass.states.get("sensor.sensor4").state == "75.0"

    turn_back_on_time = start_time + timedelta(minutes=105)
    with freeze_time(turn_back_on_time):
        async_fire_time_changed(hass, turn_back_on_time)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.5"
    assert hass.states.get("sensor.sensor2").state == "1.5"
    assert hass.states.get("sensor.sensor3").state == "0"
    assert hass.states.get("sensor.sensor4").state == "75.0"

    with freeze_time(turn_back_on_time):
        hass.states.async_set("binary_sensor.state", "on")
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.5"
    assert hass.states.get("sensor.sensor2").state == "1.5"
    assert hass.states.get("sensor.sensor3").state == "1"
    assert hass.states.get("sensor.sensor4").state == "75.0"

    end_time = start_time + timedelta(minutes=120)
    with freeze_time(end_time):
        async_fire_time_changed(hass, end_time)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "1.75"
    assert hass.states.get("sensor.sensor2").state == "1.75"
    assert hass.states.get("sensor.sensor3").state == "1"
    assert hass.states.get("sensor.sensor4").state == "87.5"


async def test_does_not_work_into_the_future(hass, recorder_mock):
    """Test history cannot tell the future.

    Verifies we do not regress https://github.com/home-assistant/core/pull/20589
    """
    hass.config.set_time_zone("UTC")
    utcnow = dt_util.utcnow()
    start_time = utcnow.replace(hour=0, minute=0, second=0, microsecond=0)

    # Start     t0        t1        t2       Startup                                       End
    # |--20min--|--20min--|--10min--|--10min--|---------30min---------|---15min--|---15min--|
    # |---on----|---on----|---on----|---on----|----------on-----------|---off----|----on----|

    def _fake_states(*args, **kwargs):
        return {
            "binary_sensor.state": [
                ha.State(
                    "binary_sensor.state",
                    "on",
                    last_changed=start_time,
                    last_updated=start_time,
                ),
            ]
        }

    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ):

        with freeze_time(start_time):
            await async_setup_component(
                hass,
                "sensor",
                {
                    "sensor": [
                        {
                            "platform": "history_stats",
                            "entity_id": "binary_sensor.state",
                            "name": "sensor1",
                            "state": "on",
                            "start": "{{ utcnow().replace(hour=23, minute=0, second=0) }}",
                            "duration": {"hours": 1},
                            "type": "time",
                        }
                    ]
                },
            )

            await async_update_entity(hass, "sensor.sensor1")
            await hass.async_block_till_done()

        assert hass.states.get("sensor.sensor1").state == STATE_UNKNOWN

        one_hour_in = start_time + timedelta(minutes=60)
        with freeze_time(one_hour_in):
            async_fire_time_changed(hass, one_hour_in)
            await hass.async_block_till_done()

        assert hass.states.get("sensor.sensor1").state == STATE_UNKNOWN

        turn_off_time = start_time + timedelta(minutes=90)
        with freeze_time(turn_off_time):
            hass.states.async_set("binary_sensor.state", "off")
            await hass.async_block_till_done()
            async_fire_time_changed(hass, turn_off_time)
            await hass.async_block_till_done()

        assert hass.states.get("sensor.sensor1").state == STATE_UNKNOWN

        turn_back_on_time = start_time + timedelta(minutes=105)
        with freeze_time(turn_back_on_time):
            async_fire_time_changed(hass, turn_back_on_time)
            await hass.async_block_till_done()

        assert hass.states.get("sensor.sensor1").state == STATE_UNKNOWN

        with freeze_time(turn_back_on_time):
            hass.states.async_set("binary_sensor.state", "on")
            await hass.async_block_till_done()

        assert hass.states.get("sensor.sensor1").state == STATE_UNKNOWN

        end_time = start_time + timedelta(minutes=120)
        with freeze_time(end_time):
            async_fire_time_changed(hass, end_time)
            await hass.async_block_till_done()

        assert hass.states.get("sensor.sensor1").state == STATE_UNKNOWN

        in_the_window = start_time + timedelta(hours=23, minutes=5)
        with freeze_time(in_the_window):
            async_fire_time_changed(hass, in_the_window)
            await hass.async_block_till_done()

        assert hass.states.get("sensor.sensor1").state == "0.08"

    past_the_window = start_time + timedelta(hours=25)
    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        return_value=[],
    ), freeze_time(past_the_window):
        async_fire_time_changed(hass, past_the_window)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == STATE_UNKNOWN

    def _fake_off_states(*args, **kwargs):
        return {
            "binary_sensor.state": [
                ha.State(
                    "binary_sensor.state",
                    "off",
                    last_changed=start_time,
                    last_updated=start_time,
                ),
            ]
        }

    past_the_window_with_data = start_time + timedelta(hours=26)
    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_off_states,
    ), freeze_time(past_the_window_with_data):
        async_fire_time_changed(hass, past_the_window_with_data)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == STATE_UNKNOWN

    at_the_next_window_with_data = start_time + timedelta(days=1, hours=23)
    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_off_states,
    ), freeze_time(at_the_next_window_with_data):
        async_fire_time_changed(hass, at_the_next_window_with_data)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "0.0"


async def test_reload_before_start_event(hass, recorder_mock):
    """Verify we can reload history_stats sensors before the start event."""
    hass.state = ha.CoreState.not_running
    hass.states.async_set("binary_sensor.test_id", "on")

    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": {
                "platform": "history_stats",
                "entity_id": "binary_sensor.test_id",
                "name": "test",
                "state": "on",
                "start": "{{ as_timestamp(now()) - 3600 }}",
                "duration": "01:00",
            },
        },
    )
    await hass.async_block_till_done()

    assert len(hass.states.async_all()) == 2

    assert hass.states.get("sensor.test")

    yaml_path = get_fixture_path("configuration.yaml", "history_stats")
    with patch.object(hass_config, "YAML_CONFIG_FILE", yaml_path):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RELOAD,
            {},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert len(hass.states.async_all()) == 2

    assert hass.states.get("sensor.test") is None
    assert hass.states.get("sensor.second_test")


async def test_measure_sliding_window(hass, recorder_mock):
    """Test the history statistics sensor with a moving end and a moving start."""
    start_time = dt_util.utcnow() - timedelta(minutes=60)
    t0 = start_time + timedelta(minutes=20)
    t1 = t0 + timedelta(minutes=10)
    t2 = t1 + timedelta(minutes=10)

    # Start     t0        t1        t2        End
    # |--20min--|--20min--|--10min--|--10min--|
    # |---off---|---on----|---off---|---on----|

    def _fake_states(*args, **kwargs):
        return {
            "binary_sensor.test_id": [
                ha.State("binary_sensor.test_id", "on", last_changed=t0),
                ha.State("binary_sensor.test_id", "off", last_changed=t1),
                ha.State("binary_sensor.test_id", "on", last_changed=t2),
            ]
        }

    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": [
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor1",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ as_timestamp(now()) + 3600 }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor2",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ as_timestamp(now()) + 3600 }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor3",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ as_timestamp(now()) + 3600 }}",
                    "type": "count",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor4",
                    "state": "on",
                    "start": "{{ as_timestamp(now()) - 3600 }}",
                    "end": "{{ as_timestamp(now()) + 3600 }}",
                    "type": "ratio",
                },
            ]
        },
    )
    await hass.async_block_till_done()

    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ), freeze_time(start_time):
        for i in range(1, 5):
            await async_update_entity(hass, f"sensor.sensor{i}")
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "0.83"
    assert hass.states.get("sensor.sensor2").state == "0.83"
    assert hass.states.get("sensor.sensor3").state == "1"
    assert hass.states.get("sensor.sensor4").state == "41.7"

    past_next_update = start_time + timedelta(minutes=30)
    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ), freeze_time(past_next_update):
        async_fire_time_changed(hass, past_next_update)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "0.83"
    assert hass.states.get("sensor.sensor2").state == "0.83"
    assert hass.states.get("sensor.sensor3").state == "1"
    assert hass.states.get("sensor.sensor4").state == "41.7"


async def test_measure_from_end_going_backwards(hass, recorder_mock):
    """Test the history statistics sensor with a moving end and a duration to find the start."""
    start_time = dt_util.utcnow() - timedelta(minutes=60)
    t0 = start_time + timedelta(minutes=20)
    t1 = t0 + timedelta(minutes=10)
    t2 = t1 + timedelta(minutes=10)

    # Start     t0        t1        t2        End
    # |--20min--|--20min--|--10min--|--10min--|
    # |---off---|---on----|---off---|---on----|

    def _fake_states(*args, **kwargs):
        return {
            "binary_sensor.test_id": [
                ha.State("binary_sensor.test_id", "on", last_changed=t0),
                ha.State("binary_sensor.test_id", "off", last_changed=t1),
                ha.State("binary_sensor.test_id", "on", last_changed=t2),
            ]
        }

    await async_setup_component(
        hass,
        "sensor",
        {
            "sensor": [
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor1",
                    "state": "on",
                    "duration": {"hours": 1},
                    "end": "{{ now() }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor2",
                    "state": "on",
                    "duration": {"hours": 1},
                    "end": "{{ now() }}",
                    "type": "time",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor3",
                    "state": "on",
                    "duration": {"hours": 1},
                    "end": "{{ now() }}",
                    "type": "count",
                },
                {
                    "platform": "history_stats",
                    "entity_id": "binary_sensor.test_id",
                    "name": "sensor4",
                    "state": "on",
                    "duration": {"hours": 1},
                    "end": "{{ now() }}",
                    "type": "ratio",
                },
            ]
        },
    )
    await hass.async_block_till_done()

    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ), freeze_time(start_time):
        for i in range(1, 5):
            await async_update_entity(hass, f"sensor.sensor{i}")
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "0.83"
    assert hass.states.get("sensor.sensor2").state == "0.83"
    assert hass.states.get("sensor.sensor3").state == "1"
    assert hass.states.get("sensor.sensor4").state == "83.3"

    past_next_update = start_time + timedelta(minutes=30)
    with patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ), freeze_time(past_next_update):
        async_fire_time_changed(hass, past_next_update)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.sensor1").state == "0.83"
    assert hass.states.get("sensor.sensor2").state == "0.83"
    assert hass.states.get("sensor.sensor3").state == "1"
    assert hass.states.get("sensor.sensor4").state == "83.3"


async def test_end_time_with_microseconds_zeroed(hass, recorder_mock):
    """Test the history statistics sensor that has the end time microseconds zeroed out."""
    hass.config.set_time_zone("Europe/Berlin")
    start_of_today = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_time = start_of_today + timedelta(minutes=60)
    t0 = start_time + timedelta(minutes=20)
    t1 = t0 + timedelta(minutes=10)
    t2 = t1 + timedelta(minutes=10)
    time_200 = start_of_today + timedelta(hours=2)

    def _fake_states(*args, **kwargs):
        return {
            "binary_sensor.heatpump_compressor_state": [
                ha.State(
                    "binary_sensor.heatpump_compressor_state", "on", last_changed=t0
                ),
                ha.State(
                    "binary_sensor.heatpump_compressor_state",
                    "off",
                    last_changed=t1,
                ),
                ha.State(
                    "binary_sensor.heatpump_compressor_state", "on", last_changed=t2
                ),
            ]
        }

    with freeze_time(time_200), patch(
        "homeassistant.components.recorder.history.state_changes_during_period",
        _fake_states,
    ):
        await async_setup_component(
            hass,
            "sensor",
            {
                "sensor": [
                    {
                        "platform": "history_stats",
                        "entity_id": "binary_sensor.heatpump_compressor_state",
                        "name": "heatpump_compressor_today",
                        "state": "on",
                        "start": "{{ now().replace(hour=0, minute=0, second=0, microsecond=0) }}",
                        "end": "{{ now().replace(microsecond=0) }}",
                        "type": "time",
                    },
                ]
            },
        )
        await hass.async_block_till_done()
        await async_update_entity(hass, "sensor.heatpump_compressor_today")
        await hass.async_block_till_done()
        assert hass.states.get("sensor.heatpump_compressor_today").state == "1.83"
        async_fire_time_changed(hass, time_200)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.heatpump_compressor_today").state == "1.83"
        hass.states.async_set("binary_sensor.heatpump_compressor_state", "off")
        await hass.async_block_till_done()

    time_400 = start_of_today + timedelta(hours=4)
    with freeze_time(time_400):
        async_fire_time_changed(hass, time_400)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.heatpump_compressor_today").state == "1.83"
        hass.states.async_set("binary_sensor.heatpump_compressor_state", "on")
        await hass.async_block_till_done()
    time_600 = start_of_today + timedelta(hours=6)
    with freeze_time(time_600):
        async_fire_time_changed(hass, time_600)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.heatpump_compressor_today").state == "3.83"
    rolled_to_next_day = start_of_today + timedelta(days=1)
    assert rolled_to_next_day.hour == 0
    assert rolled_to_next_day.minute == 0
    assert rolled_to_next_day.second == 0
    assert rolled_to_next_day.microsecond == 0

    with freeze_time(rolled_to_next_day):
        async_fire_time_changed(hass, rolled_to_next_day)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.heatpump_compressor_today").state == "0.0"
