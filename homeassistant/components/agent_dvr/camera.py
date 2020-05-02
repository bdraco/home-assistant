"""Support for Agent camera streaming."""
from datetime import timedelta
import logging

from agent import AgentError

from homeassistant.components.camera import (
    STATE_IDLE,
    STATE_RECORDING,
    STATE_STREAMING,
    SUPPORT_ON_OFF,
    SUPPORT_STREAM,
)
from homeassistant.components.mjpeg.camera import (
    CONF_MJPEG_URL,
    CONF_STILL_IMAGE_URL,
    MjpegCamera,
    filter_urllib3_logging,
)
from homeassistant.const import ATTR_ATTRIBUTION, CONF_NAME
from homeassistant.helpers import entity_platform

from .const import (
    ATTRIBUTION,
    CAMERA_SCAN_INTERVAL_SECS,
    CONNECTION,
    DOMAIN as AGENT_DOMAIN,
)

SCAN_INTERVAL = timedelta(seconds=CAMERA_SCAN_INTERVAL_SECS)

_LOGGER = logging.getLogger(__name__)

_DEV_EN_ALT = "enable_alerts"
_DEV_DS_ALT = "disable_alerts"
_DEV_EN_REC = "start_recording"
_DEV_DS_REC = "stop_recording"
_DEV_SNAP = "snapshot"

CAMERA_SERVICES = {
    _DEV_EN_ALT: "async_enable_alerts",
    _DEV_DS_ALT: "async_disable_alerts",
    _DEV_EN_REC: "async_start_recording",
    _DEV_DS_REC: "async_stop_recording",
    _DEV_SNAP: "async_snapshot",
}


async def async_setup_entry(
    hass, config_entry, async_add_entities, discovery_info=None
):
    """Set up the Agent cameras."""
    filter_urllib3_logging()
    cameras = []

    server = hass.data[AGENT_DOMAIN][config_entry.entry_id][CONNECTION]
    server.cameras = []
    if not server.deviceList:
        _LOGGER.warning("Could not fetch cameras from Agent server")
        return

    for device in server.deviceList:
        if device.typeID == 2:
            camera = AgentCamera(device)
            cameras.append(camera)
            server.cameras.append(camera)

    async_add_entities(cameras)

    platform = entity_platform.current_platform.get()
    for service, method in CAMERA_SERVICES.items():
        platform.async_register_entity_service(service, {}, method)

    return True


class AgentCamera(MjpegCamera):
    """Representation of an Agent Device Stream."""

    def __init__(self, device, enabled_default: bool = True):
        """Initialize as a subclass of MjpegCamera."""
        self._servername = device.client.name
        self.server_url = device.client._server_url

        device_info = {
            CONF_NAME: device.name,
            CONF_MJPEG_URL: f"{self.server_url}{device.mjpeg_image_url}&size=640x480",
            CONF_STILL_IMAGE_URL: f"{self.server_url}{device.still_image_url}&size=640x480",
        }
        self.device = device
        self._should_poll = True
        self._removed = False
        self._name = f"{self._servername} {device.name}"
        self._stream_url = f"{self.server_url}{device.mp4_url}"
        self._unique_id = f"{device._client.unique}_{device.typeID}_{device.id}"
        self._enabled_default = enabled_default
        super().__init__(device_info)

    @property
    def device_info(self):
        """Return the device info for adding the entity to the agent object."""
        return {
            "identifiers": {(AGENT_DOMAIN, self._unique_id)},
            "name": self._name,
            "manufacturer": "Agent",
            "model": "Camera",
            "sw_version": self.device.client.version,
        }

    async def async_update(self):
        """Update our state from the Agent API."""
        try:
            await self.device.update()
            if self._removed:
                _LOGGER.error("%s reacquired", self._name)
            self._removed = False
        except AgentError:
            if self.device.client.is_available:  # server still available - camera error
                if not self._removed:
                    _LOGGER.error("%s lost", self._name)
                    self._removed = True

    @property
    def state_attributes(self):
        """Return the Agent DVR camera state attributes."""
        return {
            ATTR_ATTRIBUTION: ATTRIBUTION,
            "editable": False,
            "enabled": self.enabled,
            "connected": self.connected,
            "detected": self.is_detected,
            "alerted": self.is_alerted,
            "recording": self.is_recording,
            "has_ptz": self.device.has_ptz,
            "motion_detection_enabled": self.device.detector_active,
            "alerts_enabled": self.device.alerts_active,
        }

    @property
    def is_recording(self) -> bool:
        """Return whether the monitor is recording."""
        return self.device.recording

    @property
    def is_alerted(self) -> bool:
        """Return whether the monitor has alerted."""
        return self.device.alerted

    @property
    def is_detected(self) -> bool:
        """Return whether the monitor has alerted."""
        return self.device.detected

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.device.client.is_available

    @property
    def connected(self) -> bool:
        """Return True if entity is connected."""
        return self.device.connected

    @property
    def enabled(self) -> bool:
        """Return True if entity is enabled."""
        return self.device.online

    @property
    def supported_features(self) -> int:
        """Return supported features."""
        return SUPPORT_ON_OFF | SUPPORT_STREAM

    @property
    def is_on(self) -> bool:
        """Return true if on."""
        return self.device.online

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        if self.enabled:
            return "mdi:camcorder"
        return "mdi:camcorder-off"

    @property
    def state(self):
        """Return the camera state."""
        if self.device.recording:
            return STATE_RECORDING
        if self.device.online:
            return STATE_STREAMING
        return STATE_IDLE

    async def stream_source(self) -> str:
        """Return the mp4 stream source."""
        return self._stream_url

    @property
    def unique_id(self) -> str:
        """Return a unique identifier for this agent object."""
        return f"{self._unique_id}"

    async def async_enable_alerts(self):
        """Enable alerts."""
        await self.device.alerts_on()

    async def async_disable_alerts(self):
        """Disable alerts."""
        await self.device.alerts_off()

    async def async_enable_motion_detection(self):
        """Enable motion detection."""
        await self.device.detector_on()

    async def async_disable_motion_detection(self):
        """Disable motion detection."""
        await self.device.detector_off()

    async def async_start_recording(self):
        """Start recording."""
        await self.device.record()

    async def async_stop_recording(self):
        """Stop recording."""
        await self.device.record_stop()

    async def async_turn_on(self):
        """Enable the camera."""
        await self.device.enable()

    async def async_toggle(self):
        """Enable/disable the camera."""
        if self.device.online:
            await self.device.disable()
        else:
            await self.device.enable()

    async def async_snapshot(self):
        """Take a snapshot."""
        await self.device.snapshot()

    async def async_turn_off(self):
        """Disable the camera."""
        await self.device.disable()
