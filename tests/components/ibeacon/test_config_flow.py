"""Test the ibeacon config flow."""
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.components.ibeacon.const import CONF_ALLOW_NAMELESS_UUIDS, DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry


async def test_setup_user_no_bluetooth(
    hass: HomeAssistant, mock_bluetooth_adapters: None
) -> None:
    """Test setting up via user interaction when bluetooth is not enabled."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "bluetooth_not_available"


async def test_setup_user(hass: HomeAssistant, enable_bluetooth: None) -> None:
    """Test setting up via user interaction with bluetooth enabled."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    with patch("homeassistant.components.ibeacon.async_setup_entry", return_value=True):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "iBeacon Tracker"
    assert result2["data"] == {}


async def test_setup_user_already_setup(
    hass: HomeAssistant, enable_bluetooth: None
) -> None:
    """Test setting up via user when already setup ."""
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow(hass: HomeAssistant, enable_bluetooth: None) -> None:
    """Test config flow options."""
    config_entry = MockConfigEntry(domain=DOMAIN)
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    # test save invalid uuid
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "new_uuid": "invalid",
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {"new_uuid": "invalid_uuid_format"}

    # test save new uuid
    uuid = "daa4b6bb-b77a-4662-aeb8-b3ed56454091"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "new_uuid": uuid,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ALLOW_NAMELESS_UUIDS: [uuid]}

    # restart
    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    # delete
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_ALLOW_NAMELESS_UUIDS: [],
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ALLOW_NAMELESS_UUIDS: []}
