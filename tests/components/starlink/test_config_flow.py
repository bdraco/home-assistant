"""Test the Starlink config flow."""
from homeassistant import data_entry_flow
from homeassistant.components.starlink.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.core import HomeAssistant

from .patchers import DEVICE_FOUND_PATCHER, NO_DEVICE_PATCHER, SETUP_ENTRY_PATCHER


async def test_flow_user_fails_no_dishy(hass: HomeAssistant) -> None:
    """Test user initialized flow when Starlink is available."""
    user_input = {CONF_IP_ADDRESS: "192.168.100.1:9200"}

    with NO_DEVICE_PATCHER, SETUP_ENTRY_PATCHER:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=user_input,
        )
        await hass.async_block_till_done()

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"]
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()


async def test_flow_user_success(hass: HomeAssistant) -> None:
    """Test user initialized flow when Starlink is available."""
    user_input = {CONF_IP_ADDRESS: "192.168.100.1:9200"}

    with DEVICE_FOUND_PATCHER, SETUP_ENTRY_PATCHER:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=user_input,
        )
        await hass.async_block_till_done()

    assert not result["errors"]
    assert result["data"] == user_input
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
