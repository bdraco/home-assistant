"""Message templates for websocket commands."""

from functools import lru_cache
import json
from typing import Any, Dict

import voluptuous as vol

from homeassistant.core import Event
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.json import JSONEncoder

from . import const

# mypy: allow-untyped-defs

# Minimal requirements of a message
MINIMAL_MESSAGE_SCHEMA = vol.Schema(
    {vol.Required("id"): cv.positive_int, vol.Required("type"): cv.string},
    extra=vol.ALLOW_EXTRA,
)

# Base schema to extend by message handlers
BASE_COMMAND_MESSAGE_SCHEMA = vol.Schema({vol.Required("id"): cv.positive_int})


def result_message(iden, result=None):
    """Return a success result message."""
    return {"id": iden, "type": const.TYPE_RESULT, "success": True, "result": result}


def error_message(iden, code, message):
    """Return an error result message."""
    return {
        "id": iden,
        "type": const.TYPE_RESULT,
        "success": False,
        "error": {"code": code, "message": message},
    }


def event_message(iden: int, event: Any) -> Dict:
    """Return an event message."""
    return {"id": iden, "type": "event", "event": event}


@lru_cache  # type: ignore
def cached_event_message(iden: int, event: Event) -> str:
    """Return an event message.

    Serialize to json once per message.

    Since we can have many clients connected that are
    all getting many of the same events (mostly state changed)
    we can avoid serializing the same data for each connection.
    """
    return json.dumps(event_message(iden, event), cls=JSONEncoder, allow_nan=False)
