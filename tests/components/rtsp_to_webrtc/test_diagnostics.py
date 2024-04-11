"""Test nest diagnostics."""

from typing import Any
from unittest.mock import ANY

from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant

from .conftest import ComponentSetup

from tests.common import MockConfigEntry
from tests.components.diagnostics import get_diagnostics_for_config_entry
from tests.typing import ClientSessionGenerator

THERMOSTAT_TYPE = "sdm.devices.types.THERMOSTAT"


async def test_entry_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    rtsp_to_webrtc_client: Any,
    setup_integration: ComponentSetup,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test config entry diagnostics."""
    await setup_integration()

    assert await get_diagnostics_for_config_entry(hass, hass_client, config_entry) == {
        "discovery": {"attempt": ANY, "web.failure": ANY, "webrtc.success": ANY},
        "web": {},
        "webrtc": {},
    }
