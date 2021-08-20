"""Models helper class for the usb integration."""
from __future__ import annotations

from typing import TypedDict


class USBDevice(TypedDict):
    """A usb device."""

    device: str
    vid: str
    pid: str
    serial_number: str | None
    manufacturer: str | None
    description: str | None
