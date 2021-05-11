"""Fixtures for Samsung TV."""
from unittest.mock import Mock, patch

import pytest

import homeassistant.util.dt as dt_util


@pytest.fixture(name="remote")
def remote_fixture():
    """Patch the samsungctl Remote."""
    with patch(
        "homeassistant.components.samsungtv.bridge.Remote"
    ) as remote_class, patch(
        "homeassistant.components.samsungtv.config_flow.socket.gethostbyname"
    ):
        remote = Mock()
        remote.__enter__ = Mock()
        remote.__exit__ = Mock()
        remote_class.return_value = remote
        yield remote


@pytest.fixture(name="remotews")
def remotews_fixture():
    """Patch the samsungtvws SamsungTVWS."""
    with patch(
        "homeassistant.components.samsungtv.bridge.SamsungTVWS"
    ) as remotews_class, patch(
        "homeassistant.components.samsungtv.config_flow.socket.gethostbyname"
    ):
        remotews = Mock()
        remotews.__enter__ = Mock()
        remotews.__exit__ = Mock()
        remotews.rest_device_info.return_value = {"device": {"type": "Samsung SmartTV"}}
        remotews_class.return_value = remotews
        remotews_class().__enter__().token = "FAKE_TOKEN"
        yield remotews


@pytest.fixture(name="delay")
def delay_fixture():
    """Patch the delay script function."""
    with patch(
        "homeassistant.components.samsungtv.media_player.Script.async_run"
    ) as delay:
        yield delay


@pytest.fixture
def mock_now():
    """Fixture for dtutil.now."""
    return dt_util.utcnow()
