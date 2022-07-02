"""Support for LIFX."""

from __future__ import annotations

from typing import Any

from aiolifx import products
from aiolifx.aiolifx import Light
from awesomeversion import AwesomeVersion

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_XY_COLOR,
    preprocess_turn_on_alternatives,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
import homeassistant.util.color as color_util

from .const import DOMAIN

FIX_MAC_FW = AwesomeVersion("3.70")


@callback
def async_entry_is_legacy(entry: ConfigEntry) -> bool:
    """Check if a config entry is the legacy shared one."""
    return entry.unique_id is None or entry.unique_id == DOMAIN


def convert_8_to_16(value: int) -> int:
    """Scale an 8 bit level into 16 bits."""
    return (value << 8) | value


def convert_16_to_8(value: int) -> int:
    """Scale a 16 bit level into 8 bits."""
    return value >> 8


def lifx_features(bulb: Light) -> dict[str, Any]:
    """Return a feature map for this bulb, or a default map if unknown."""
    features: dict[str, Any] = (
        products.features_map.get(bulb.product) or products.features_map[1]
    )
    return features


def find_hsbk(hass: HomeAssistant, **kwargs: Any) -> list[float | int | None] | None:
    """Find the desired color from a number of possible inputs.

    Hue, Saturation, Brightness, Kelvin
    """
    hue, saturation, brightness, kelvin = [None] * 4

    preprocess_turn_on_alternatives(hass, kwargs)  # type: ignore[no-untyped-call]

    if ATTR_HS_COLOR in kwargs:
        hue, saturation = kwargs[ATTR_HS_COLOR]
    elif ATTR_RGB_COLOR in kwargs:
        hue, saturation = color_util.color_RGB_to_hs(*kwargs[ATTR_RGB_COLOR])
    elif ATTR_XY_COLOR in kwargs:
        hue, saturation = color_util.color_xy_to_hs(*kwargs[ATTR_XY_COLOR])

    if hue is not None:
        assert saturation is not None
        hue = int(hue / 360 * 65535)
        saturation = int(saturation / 100 * 65535)
        kelvin = 3500

    if ATTR_COLOR_TEMP in kwargs:
        kelvin = int(
            color_util.color_temperature_mired_to_kelvin(kwargs[ATTR_COLOR_TEMP])
        )
        saturation = 0

    if ATTR_BRIGHTNESS in kwargs:
        brightness = convert_8_to_16(kwargs[ATTR_BRIGHTNESS])

    hsbk = [hue, saturation, brightness, kelvin]
    return None if hsbk == [None] * 4 else hsbk


def merge_hsbk(
    base: list[float | int | None], change: list[float | int | None] | None
) -> list[float | int | None] | None:
    """Copy change on top of base, except when None.

    Hue, Saturation, Brightness, Kelvin
    """
    if change is None:
        return None
    return [b if c is None else c for b, c in zip(base, change)]


def _get_mac_offset(mac_addr: str, offset: int) -> str:
    octets = [int(octet, 16) for octet in mac_addr.split(":")]
    octets[5] = (octets[5] + offset) % 256
    return ":".join(f"{octet:02x}" for octet in octets)


def _off_by_one_mac(firmware: str) -> bool:
    """Check if the firmware version has the off by one mac."""
    return bool(firmware and AwesomeVersion(firmware) >= FIX_MAC_FW)


def get_real_mac_addr(mac_addr: str, firmware: str) -> str:
    """Increment the last byte of the mac address by one for FW>3.70."""
    return _get_mac_offset(mac_addr, 1) if _off_by_one_mac(firmware) else mac_addr


def real_mac_to_lifx_mac_addr(mac_addr: str) -> str:
    """Decrement the last byte of the mac address by one for FW>3.70."""
    return _get_mac_offset(mac_addr, -1)
