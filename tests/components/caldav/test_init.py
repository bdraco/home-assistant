"""Test the Caldav component."""

from unittest.mock import patch

from caldav.lib.error import DAVError

from homeassistant.components.caldav.const import CONF_DAYS, DOMAIN
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry


async def test_async_setup_entry(hass: HomeAssistant, mock_connect):
    """Test setup entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_USER,
        data={
            CONF_URL: "url",
            CONF_USERNAME: "username",
            CONF_PASSWORD: "any",
            CONF_DAYS: 1,
            CONF_VERIFY_SSL: True,
        },
        entry_id=1,
        unique_id="username:url",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not hass.data.get(DOMAIN)


async def test_dav_error_setup_entry(hass: HomeAssistant):
    """Test setup entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_USER,
        data={
            CONF_URL: "url",
            CONF_USERNAME: "username",
            CONF_PASSWORD: "any",
            CONF_DAYS: 1,
            CONF_VERIFY_SSL: True,
        },
        entry_id=1,
        unique_id="username:url",
    )
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.caldav.caldav.DAVClient.principal",
        side_effect=DAVError,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
