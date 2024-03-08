"""Helper to gather system info."""

from __future__ import annotations

from functools import cache
from getpass import getuser
import logging
import os
import platform
from typing import Any

from homeassistant.const import __version__ as current_version
from homeassistant.core import HomeAssistant
from homeassistant.loader import bind_hass
from homeassistant.util.package import is_docker_env, is_virtual_env

_LOGGER = logging.getLogger(__name__)


@cache
def is_official_image() -> bool:
    """Return True if Home Assistant is running in an official container."""
    return os.path.isfile("/OFFICIAL_IMAGE")


# Cache the result of getuser() because it can call getpwuid() which
# can do blocking I/O to look up the username in /etc/passwd.
cached_get_user = cache(getuser)


@bind_hass
async def async_get_system_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return info about the system."""
    # Local import to avoid circular dependencies
    # pylint: disable-next=import-outside-toplevel
    from homeassistant.components import hassio

    is_hassio = hassio.is_hassio(hass)

    info_object = {
        "installation_type": "Unknown",
        "version": current_version,
        "dev": "dev" in current_version,
        "hassio": is_hassio,
        "virtualenv": is_virtual_env(),
        "python_version": platform.python_version(),
        "docker": False,
        "arch": platform.machine(),
        "timezone": str(hass.config.time_zone),
        "os_name": platform.system(),
        "os_version": platform.release(),
    }

    try:
        info_object["user"] = cached_get_user()
    except KeyError:
        info_object["user"] = None

    if platform.system() == "Darwin":
        info_object["os_version"] = platform.mac_ver()[0]
    elif platform.system() == "Linux":
        info_object["docker"] = is_docker_env()

    # Determine installation type on current data
    if info_object["docker"]:
        if info_object["user"] == "root" and is_official_image():
            info_object["installation_type"] = "Home Assistant Container"
        else:
            info_object["installation_type"] = "Unsupported Third Party Container"

    elif is_virtual_env():
        info_object["installation_type"] = "Home Assistant Core"

    # Enrich with Supervisor information
    if is_hassio:
        if not (info := hassio.get_info(hass)):
            _LOGGER.warning("No Home Assistant Supervisor info available")
            info = {}

        host = hassio.get_host_info(hass) or {}
        info_object["supervisor"] = info.get("supervisor")
        info_object["host_os"] = host.get("operating_system")
        info_object["docker_version"] = info.get("docker")
        info_object["chassis"] = host.get("chassis")

        if info.get("hassos") is not None:
            info_object["installation_type"] = "Home Assistant OS"
        else:
            info_object["installation_type"] = "Home Assistant Supervised"
    elif "SUPERVISOR" in os.environ:
        # hassio is not loaded, but we know we are running supervised
        # because the SUPERVISOR env var is set
        info_object["installation_type"] = "Home Assistant Supervised"

    return info_object
