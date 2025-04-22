"""Constants for the KEM integration."""

from datetime import timedelta
from typing import Final

from aiokem import CommunicationError

DOMAIN = "kem"

CE_RT_COORDINATORS = "coordinators"  # Please name these something more specific as I don't know what CE stands for
CE_RT_KEM = "kem"
CE_RT_HOMES = "homes"

CONF_REFRESH_TOKEN = "refresh_token"

DD_DEVICES = "devices"  # Please name these something more specific as I don't know what DD stands for
DD_PRODUCT = "product"
DD_FIRMWARE_VERSION = "firmwareVersion"
DD_MODEL_NAME = "modelDisplayName"
DD_ID = "id"
DD_DISPLAY_NAME = "displayName"
DD_MAC_ADDRESS = "macAddress"
DD_IS_CONNECTED = "isConnected"

KOHLER = "Kohler"

GD_DEVICE = "device"  # Please name these something more specific as I don't know what GD stands for

CONNECTION_EXCEPTIONS = (
    TimeoutError,
    CommunicationError,
)

RPM: Final = "rpm"

SCAN_INTERVAL_MINUTES = timedelta(minutes=10)
