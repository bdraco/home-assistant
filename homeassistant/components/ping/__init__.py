"""The ping component."""
from __future__ import annotations

from functools import lru_cache

from icmplib import SocketPermissionError, ping as icmp_ping

from homeassistant.core import callback

DOMAIN = "ping"
PLATFORMS = ["binary_sensor"]

PING_ID = "ping_id"
DEFAULT_START_ID = 129
MAX_PING_ID = 65534


@callback
def async_get_next_ping_id(hass):
    """Find the next id to use in the outbound ping.

    Must be called in async
    """
    current_id = hass.data.setdefault(DOMAIN, {}).get(PING_ID, DEFAULT_START_ID)

    if current_id == MAX_PING_ID:
        next_id = DEFAULT_START_ID
    else:
        next_id = current_id + 1

    hass.data[DOMAIN][PING_ID] = next_id

    return next_id


# In python 3.9 and later, this can be converted to just be `cache`
@lru_cache(maxsize=None)
def can_use_icmp_lib_with_privilege() -> None | bool:
    """Verify we can create a raw socket."""
    try:
        icmp_ping("127.0.0.1", count=0, timeout=0)
    except SocketPermissionError:
        try:
            icmp_ping("127.0.0.1", count=0, timeout=0, privileged=False)
        except SocketPermissionError:
            # Cannot use icmplib even with privileged=False
            return None
        else:
            # Can use icmplib with privileged=False
            return False
    else:
        # Can use icmplib privileged=True
        return True
