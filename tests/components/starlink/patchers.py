"""General Starlink patchers."""
from unittest.mock import patch

from starlink_grpc import StatusDict

from homeassistant.components.starlink.coordinator import StarlinkUpdateCoordinator

SETUP_ENTRY_PATCHER = patch(
    "homeassistant.components.starlink.async_setup_entry", return_value=True
)

COORDINATOR_SUCCESS_PATCHER = patch.object(
    StarlinkUpdateCoordinator, "_async_update_data", return_value=StatusDict(id="1")
)

DEVICE_FOUND_PATCHER = patch("starlink_grpc.get_id", return_value="some-valid-id")

NO_DEVICE_PATCHER = patch("starlink_grpc.get_id", return_value=None)
