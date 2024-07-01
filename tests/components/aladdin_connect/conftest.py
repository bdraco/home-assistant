"""Test fixtures for the Aladdin Connect Garage Door integration."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

from tests.common import MockConfigEntry


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.aladdin_connect.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return an Aladdin Connect config entry."""
    return MockConfigEntry(
        domain="aladdin_connect",
        data={},
        title="test@test.com",
        unique_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        version=2,
    )
