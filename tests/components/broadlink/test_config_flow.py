"""Test the Broadlink config flow."""
import errno
import socket

import broadlink.exceptions as blke
import pytest

from homeassistant import config_entries
from homeassistant.components.broadlink.const import DOMAIN

from . import get_device

from tests.async_mock import call, patch


@pytest.fixture(autouse=True)
def broadlink_setup_fixture():
    """Mock broadlink entry setup."""
    with patch(
        "homeassistant.components.broadlink.async_setup_entry", return_value=True
    ):
        yield


async def test_flow_user_works(hass):
    """Test a config flow initiated by the user.

    Best case scenario with no errors or locks.
    """
    device = get_device("Living Room")
    mock_api = device.get_mock_api()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    with patch("broadlink.discover", return_value=[mock_api]) as mock_discover:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "finish"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": device.name},
    )

    assert result["type"] == "create_entry"
    assert result["title"] == device.name
    assert result["data"] == device.get_entry_data()

    assert mock_discover.call_count == 1
    assert mock_api.auth.call_count == 1


async def test_flow_user_already_in_progress(hass):
    """Test we do not accept more than one config flow per device."""
    device = get_device("Living Room")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[device.get_mock_api()]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[device.get_mock_api()]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "already_in_progress"


async def test_flow_user_mac_already_configured(hass):
    """Test we do not accept more than one config entry per device.

    We need to abort the flow and update the existing entry.
    """
    device = get_device("Living Room")
    mock_entry = device.get_mock_entry()
    mock_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    device.host = "192.168.1.64"
    device.timeout = 20
    mock_api = device.get_mock_api()

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"

    assert dict(mock_entry.data) == device.get_entry_data()
    assert mock_api.auth.call_count == 0


async def test_flow_user_invalid_ip_address(hass):
    """Test we handle an invalid IP address in the user step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", side_effect=OSError(errno.EINVAL, None)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "0.0.0.1"},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_host"}


async def test_flow_user_invalid_hostname(hass):
    """Test we handle an invalid hostname in the user step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", side_effect=OSError(socket.EAI_NONAME, None)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "pancakemaster.local"},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_host"}


async def test_flow_user_device_not_found(hass):
    """Test we handle a device not found in the user step."""
    device = get_device("Living Room")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_flow_user_network_unreachable(hass):
    """Test we handle a network unreachable in the user step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", side_effect=OSError(errno.ENETUNREACH, None)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.32"},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_flow_user_os_error(hass):
    """Test we handle an OS error in the user step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", side_effect=OSError()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.32"},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "unknown"}


async def test_flow_auth_authentication_error(hass):
    """Test we handle an authentication error in the auth step."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.auth.side_effect = blke.AuthenticationError()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "reset"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_flow_auth_device_offline(hass):
    """Test we handle a device offline in the auth step."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.auth.side_effect = blke.DeviceOfflineError()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "auth"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_flow_auth_firmware_error(hass):
    """Test we handle a firmware error in the auth step."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.auth.side_effect = blke.BroadlinkException()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "auth"
    assert result["errors"] == {"base": "unknown"}


async def test_flow_auth_network_unreachable(hass):
    """Test we handle a network unreachable in the auth step."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.auth.side_effect = OSError(errno.ENETUNREACH, None)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "auth"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_flow_auth_os_error(hass):
    """Test we handle an OS error in the auth step."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.auth.side_effect = OSError()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "auth"
    assert result["errors"] == {"base": "unknown"}


async def test_flow_reset_works(hass):
    """Test we finish a config flow after a factory reset."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.auth.side_effect = blke.AuthenticationError()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    with patch("broadlink.discover", return_value=[device.get_mock_api()]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": device.name},
    )

    assert result["type"] == "create_entry"
    assert result["title"] == device.name
    assert result["data"] == device.get_entry_data()


async def test_flow_unlock_works(hass):
    """Test we finish a config flow with an unlock request."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.is_locked = True

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "unlock"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"unlock": True},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": device.name},
    )

    assert result["type"] == "create_entry"
    assert result["title"] == device.name
    assert result["data"] == device.get_entry_data()

    assert mock_api.set_lock.call_args == call(False)
    assert mock_api.set_lock.call_count == 1


async def test_flow_unlock_device_offline(hass):
    """Test we handle a device offline in the unlock step."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.is_locked = True
    mock_api.set_lock.side_effect = blke.DeviceOfflineError

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"unlock": True},
    )

    assert result["type"] == "form"
    assert result["step_id"] == "unlock"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_flow_unlock_firmware_error(hass):
    """Test we handle a firmware error in the unlock step."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.is_locked = True
    mock_api.set_lock.side_effect = blke.BroadlinkException

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"unlock": True},
    )

    assert result["type"] == "form"
    assert result["step_id"] == "unlock"
    assert result["errors"] == {"base": "unknown"}


async def test_flow_unlock_network_unreachable(hass):
    """Test we handle a network unreachable in the unlock step."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.is_locked = True
    mock_api.set_lock.side_effect = OSError(errno.ENETUNREACH, None)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"unlock": True},
    )

    assert result["type"] == "form"
    assert result["step_id"] == "unlock"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_flow_unlock_os_error(hass):
    """Test we handle an OS error in the unlock step."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.is_locked = True
    mock_api.set_lock.side_effect = OSError()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"unlock": True},
    )

    assert result["type"] == "form"
    assert result["step_id"] == "unlock"
    assert result["errors"] == {"base": "unknown"}


async def test_flow_do_not_unlock(hass):
    """Test we do not unlock the device if the user does not want to."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()
    mock_api.is_locked = True

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"unlock": False},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": device.name},
    )

    assert result["type"] == "create_entry"
    assert result["title"] == device.name
    assert result["data"] == device.get_entry_data()

    assert mock_api.set_lock.call_count == 0


async def test_flow_import_works(hass):
    """Test an import flow."""
    device = get_device("Living Room")
    mock_api = device.get_mock_api()

    with patch("broadlink.discover", return_value=[mock_api]) as mock_discover:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={"host": device.host},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "finish"
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": device.name},
    )

    assert result["type"] == "create_entry"
    assert result["title"] == device.name
    assert result["data"]["host"] == device.host
    assert result["data"]["mac"] == device.mac
    assert result["data"]["type"] == device.devtype

    assert mock_api.auth.call_count == 1
    assert mock_discover.call_count == 1


async def test_flow_import_already_in_progress(hass):
    """Test we do not import more than one flow per device."""
    device = get_device("Living Room")
    data = {"host": device.host}

    with patch("broadlink.discover", return_value=[device.get_mock_api()]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
        )

    with patch("broadlink.discover", return_value=[device.get_mock_api()]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
        )

    assert result["type"] == "abort"
    assert result["reason"] == "already_in_progress"


async def test_flow_import_host_already_configured(hass):
    """Test we do not import a host that is already configured."""
    device = get_device("Living Room")
    mock_entry = device.get_mock_entry()
    mock_entry.add_to_hass(hass)
    mock_api = device.get_mock_api()

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={"host": device.host},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_flow_import_mac_already_configured(hass):
    """Test we do not import more than one config entry per device.

    We need to abort the flow and update the existing entry.
    """
    device = get_device("Living Room")
    mock_entry = device.get_mock_entry()
    mock_entry.add_to_hass(hass)

    device.host = "192.168.1.16"
    mock_api = device.get_mock_api()

    with patch("broadlink.discover", return_value=[mock_api]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={"host": device.host},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"

    assert mock_entry.data["host"] == device.host
    assert mock_entry.data["mac"] == device.mac
    assert mock_entry.data["type"] == device.devtype
    assert mock_api.auth.call_count == 0


async def test_flow_import_device_not_found(hass):
    """Test we handle a device not found in the import step."""
    with patch("broadlink.discover", return_value=[]):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={"host": "192.168.1.32"},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


async def test_flow_import_invalid_ip_address(hass):
    """Test we handle an invalid IP address in the import step."""
    with patch("broadlink.discover", side_effect=OSError(errno.EINVAL, None)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={"host": "0.0.0.1"},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "invalid_host"


async def test_flow_import_invalid_hostname(hass):
    """Test we handle an invalid hostname in the import step."""
    with patch("broadlink.discover", side_effect=OSError(socket.EAI_NONAME, None)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={"host": "hotdog.local"},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "invalid_host"


async def test_flow_import_network_unreachable(hass):
    """Test we handle a network unreachable in the import step."""
    with patch("broadlink.discover", side_effect=OSError(errno.ENETUNREACH, None)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={"host": "192.168.1.64"},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


async def test_flow_import_os_error(hass):
    """Test we handle an OS error in the import step."""
    with patch("broadlink.discover", side_effect=OSError()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={"host": "192.168.1.64"},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "unknown"


async def test_flow_reauth_works(hass):
    """Test a reauthentication flow."""
    device = get_device("Living Room")
    mock_entry = device.get_mock_entry()
    mock_entry.add_to_hass(hass)
    mock_api = device.get_mock_api()
    mock_api.auth.side_effect = blke.AuthenticationError()
    data = {"name": device.name, **device.get_entry_data()}

    with patch("broadlink.gendevice", return_value=mock_api):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reauth"}, data=data
        )

    assert result["type"] == "form"
    assert result["step_id"] == "reset"

    mock_api = device.get_mock_api()

    with patch("broadlink.discover", return_value=[mock_api]) as mock_discover:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"

    assert dict(mock_entry.data) == device.get_entry_data()
    assert mock_api.auth.call_count == 1
    assert mock_discover.call_count == 1


async def test_flow_reauth_invalid_host(hass):
    """Test we do not accept an invalid host for reauthentication.

    The MAC address cannot change.
    """
    device = get_device("Living Room")
    mock_entry = device.get_mock_entry()
    mock_entry.add_to_hass(hass)
    mock_api = device.get_mock_api()
    mock_api.auth.side_effect = blke.AuthenticationError()
    data = {"name": device.name, **device.get_entry_data()}

    with patch("broadlink.gendevice", return_value=mock_api):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reauth"}, data=data
        )

    device.mac = get_device("Office").mac
    mock_api = device.get_mock_api()

    with patch("broadlink.discover", return_value=[mock_api]) as mock_discover:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_host"}

    assert mock_discover.call_count == 1
    assert mock_api.auth.call_count == 0


async def test_flow_reauth_valid_host(hass):
    """Test we accept a valid host for reauthentication.

    The hostname/IP address may change. We need to update the entry.
    """
    device = get_device("Living Room")
    mock_entry = device.get_mock_entry()
    mock_entry.add_to_hass(hass)
    mock_api = device.get_mock_api()
    mock_api.auth.side_effect = blke.AuthenticationError()
    data = {"name": device.name, **device.get_entry_data()}

    with patch("broadlink.gendevice", return_value=mock_api):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reauth"}, data=data
        )

    device.host = "192.168.1.128"
    mock_api = device.get_mock_api()

    with patch("broadlink.discover", return_value=[mock_api]) as mock_discover:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": device.host, "timeout": device.timeout},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"

    assert mock_entry.data["host"] == device.host
    assert mock_discover.call_count == 1
    assert mock_api.auth.call_count == 1
