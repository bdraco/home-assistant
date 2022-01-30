"""Test the WS66i 6-Zone Amplifier config flow."""
from unittest.mock import patch

from homeassistant import config_entries, data_entry_flow, setup
from homeassistant.components.ws66i.const import (
    CONF_SOURCE_1,
    CONF_SOURCE_4,
    CONF_SOURCE_5,
    CONF_SOURCES,
    DOMAIN,
)
from homeassistant.const import CONF_IP_ADDRESS

from tests.common import MockConfigEntry

CONFIG = {
    CONF_IP_ADDRESS: "1.1.1.1",
    CONF_SOURCE_1: "one",
    CONF_SOURCE_4: "four",
    CONF_SOURCE_5: "    ",
}


async def test_form(hass):
    """Test we get the form."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["errors"] == {}

    with patch(
        "homeassistant.components.ws66i.config_flow.get_ws66i",
    ) as mock_ws66i, patch(
        "homeassistant.components.ws66i.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:

        ws66i_instance = mock_ws66i.return_value

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], CONFIG
        )
        await hass.async_block_till_done()

        ws66i_instance.open.assert_called_once()
        ws66i_instance.close.assert_called_once()

    assert result2["type"] == "create_entry"
    assert result2["title"] == "WS66i Amp"
    assert result2["data"] == {
        CONF_IP_ADDRESS: CONFIG[CONF_IP_ADDRESS],
        CONF_SOURCES: {"1": CONFIG[CONF_SOURCE_1], "4": CONFIG[CONF_SOURCE_4]},
    }

    assert len(mock_setup_entry.mock_calls) == 1


async def test_form_cannot_connect(hass):
    """Test cannot connect error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("homeassistant.components.ws66i.config_flow.get_ws66i") as mock_ws66i:
        ws66i_instance = mock_ws66i.return_value
        ws66i_instance.open.side_effect = ConnectionError
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], CONFIG
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_form_wrong_ip(hass):
    """Test cannot connect error with bad IP."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("homeassistant.components.ws66i.config_flow.get_ws66i") as mock_ws66i:
        ws66i_instance = mock_ws66i.return_value
        ws66i_instance.zone_status.return_value = None
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], CONFIG
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_generic_exception(hass):
    """Test generic exception."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("homeassistant.components.ws66i.config_flow.get_ws66i") as mock_ws66i:
        ws66i_instance = mock_ws66i.return_value
        ws66i_instance.open.side_effect = Exception
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], CONFIG
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "unknown"}


async def test_options_flow(hass):
    """Test config flow options."""
    conf = {CONF_IP_ADDRESS: "1.1.1.1", CONF_SOURCES: {"4": "four"}}

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=conf,
        options={CONF_SOURCES: {"4": "four"}},
    )
    config_entry.add_to_hass(hass)

    with patch("homeassistant.components.ws66i.async_setup_entry", return_value=True):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(config_entry.entry_id)

        assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={CONF_SOURCE_1: "one", CONF_SOURCE_4: "", CONF_SOURCE_5: "five"},
        )

        assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
        assert config_entry.options[CONF_SOURCES] == {"1": "one", "5": "five"}
