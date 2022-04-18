"""The tests for input_datetime recorder."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components import input_datetime
from homeassistant.components.input_datetime import CONF_HAS_DATE, CONF_HAS_TIME
from homeassistant.components.recorder.models import StateAttributes, States
from homeassistant.components.recorder.util import session_scope
from homeassistant.const import ATTR_FRIENDLY_NAME
from homeassistant.core import State
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from tests.common import async_fire_time_changed, async_init_recorder_component
from tests.components.recorder.common import async_wait_recording_done_without_instance


async def test_exclude_attributes(hass):
    """Test input_datetime registered attributes to be excluded."""
    await async_init_recorder_component(hass)
    await hass.async_block_till_done()
    assert await async_setup_component(
        hass,
        input_datetime.DOMAIN,
        {
            input_datetime.DOMAIN: {
                "test_datetime_initial_with_tz": {
                    "has_time": True,
                    "has_date": True,
                    "initial": "2020-12-13 10:00:00+01:00",
                },
                "test_datetime_initial_without_tz": {
                    "has_time": True,
                    "has_date": True,
                    "initial": "2020-12-13 10:00:00",
                },
                "test_time_initial": {
                    "has_time": True,
                    "has_date": False,
                    "initial": "10:00:00",
                },
            }
        },
    )
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
    await hass.async_block_till_done()
    await async_wait_recording_done_without_instance(hass)

    def _fetch_states() -> list[State]:
        with session_scope(hass=hass) as session:
            native_states = []
            for db_state, db_state_attributes in session.query(States, StateAttributes):
                state = db_state.to_native()
                state.attributes = db_state_attributes.to_native()
                native_states.append(state)
            return native_states

    states: list[State] = await hass.async_add_executor_job(_fetch_states)
    assert len(states) > 1
    for state in states:
        assert CONF_HAS_DATE not in state.attributes
        assert CONF_HAS_TIME not in state.attributes
        assert ATTR_FRIENDLY_NAME in state.attributes
