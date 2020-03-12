"""Tests for the Synology DSM config flow."""
import logging
from unittest.mock import MagicMock, Mock, patch

import pytest

from homeassistant import data_entry_flow
from homeassistant.components.synology_dsm.const import (
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_PORT_SSL,
    DEFAULT_SSL,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
)
from homeassistant.helpers.typing import HomeAssistantType

from tests.common import MockConfigEntry

_LOGGER = logging.getLogger(__name__)


NAME = "My Syno"
HOST = "nas.meontheinternet.com"
HOST_2 = "nas.worldwide.me"
PORT = 1234
SSL = True
USERNAME = "Home_Assistant"
PASSWORD = "password"


@pytest.fixture(name="service")
def mock_controller_service():
    """Mock a successful service."""
    with patch(
        "homeassistant.components.synology_dsm.config_flow.SynologyDSM"
    ) as service_mock:
        service_mock.return_value.update = Mock()
        service_mock.return_value.storage = Mock(disks=[], volumes=[])
        service_mock.return_value.utilisation = Mock(cpu_user_load=1)
        yield service_mock


@pytest.fixture(name="service_failed")
def mock_controller_service_failed():
    """Mock a failed service."""
    with patch(
        "homeassistant.components.synology_dsm.config_flow.SynologyDSM"
    ) as service_mock:
        service_mock.return_value.update = Mock()
        service_mock.return_value.storage = Mock(disks=None, volumes=None)
        service_mock.return_value.utilisation = Mock(cpu_user_load=None)
        yield service_mock


async def test_user(hass: HomeAssistantType, service: MagicMock):
    """Test user config."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=None
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "user"

    # test with all provided
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            CONF_NAME: NAME,
            CONF_HOST: HOST,
            CONF_PORT: PORT,
            CONF_SSL: SSL,
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
        },
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["result"].unique_id == f"{HOST}:{PORT}"
    assert result["title"] == HOST
    assert result["data"][CONF_NAME] == NAME
    assert result["data"][CONF_HOST] == HOST
    assert result["data"][CONF_PORT] == PORT
    assert result["data"][CONF_SSL] == SSL
    assert result["data"][CONF_USERNAME] == USERNAME
    assert result["data"][CONF_PASSWORD] == PASSWORD

    # test without port + False SSL
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            CONF_NAME: NAME,
            CONF_HOST: HOST,
            CONF_SSL: False,
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
        },
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["result"].unique_id == f"{HOST}:{DEFAULT_PORT}"
    assert result["title"] == HOST
    assert result["data"][CONF_NAME] == NAME
    assert result["data"][CONF_HOST] == HOST
    assert result["data"][CONF_PORT] == DEFAULT_PORT
    assert not result["data"][CONF_SSL]
    assert result["data"][CONF_USERNAME] == USERNAME
    assert result["data"][CONF_PASSWORD] == PASSWORD


async def test_import(hass: HomeAssistantType, service: MagicMock):
    """Test import step."""
    # import with minimum setup
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={CONF_HOST: HOST, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["result"].unique_id == f"{HOST}:{DEFAULT_PORT_SSL}"
    assert result["title"] == HOST
    assert result["data"][CONF_NAME] == DEFAULT_NAME
    assert result["data"][CONF_HOST] == HOST
    assert result["data"][CONF_PORT] == DEFAULT_PORT_SSL
    assert result["data"][CONF_SSL] == DEFAULT_SSL
    assert result["data"][CONF_USERNAME] == USERNAME
    assert result["data"][CONF_PASSWORD] == PASSWORD

    # import with all
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={
            CONF_NAME: NAME,
            CONF_HOST: HOST_2,
            CONF_PORT: PORT,
            CONF_SSL: SSL,
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
        },
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result["result"].unique_id == f"{HOST_2}:{PORT}"
    assert result["title"] == HOST_2
    assert result["data"][CONF_NAME] == NAME
    assert result["data"][CONF_HOST] == HOST_2
    assert result["data"][CONF_PORT] == PORT
    assert result["data"][CONF_SSL] == SSL
    assert result["data"][CONF_USERNAME] == USERNAME
    assert result["data"][CONF_PASSWORD] == PASSWORD


async def test_abort_if_already_setup(hass: HomeAssistantType):
    """Test we abort if the account is already setup."""
    MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: HOST, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
        unique_id=f"{HOST}:{DEFAULT_PORT_SSL}",
    ).add_to_hass(hass)

    # Should fail, same HOST:PORT (import)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={CONF_HOST: HOST, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_ABORT
    assert result["reason"] == "already_configured"

    # Should fail, same HOST:PORT (flow)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_HOST: HOST, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_ABORT
    assert result["reason"] == "already_configured"


async def test_connection_failed(hass: HomeAssistantType, service_failed: MagicMock):
    """Test when we have errors during connection."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_HOST: HOST, CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD},
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["errors"] == {"base": "unknown"}
