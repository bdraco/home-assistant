"""Class to hold all camera accessories."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import logging
import subprocess
import sys
from typing import Any

from pyhap.camera import (
    VIDEO_CODEC_PARAM_LEVEL_TYPES,
    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES,
    Camera as PyhapCamera,
)
from pyhap.const import CATEGORY_CAMERA
from pyhap.util import callback as pyhap_callback

from homeassistant.components import camera
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HassJobType,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util.async_ import create_eager_task

from .accessories import TYPES, HomeDriver
from .const import (
    CHAR_MOTION_DETECTED,
    CONF_AUDIO_CODEC,
    CONF_AUDIO_PACKET_SIZE,
    CONF_LINKED_MOTION_SENSOR,
    CONF_MAX_FPS,
    CONF_MAX_HEIGHT,
    CONF_MAX_WIDTH,
    CONF_STREAM_ADDRESS,
    CONF_STREAM_COUNT,
    CONF_STREAM_SOURCE,
    CONF_SUPPORT_AUDIO,
    CONF_VIDEO_CODEC,
    CONF_VIDEO_PACKET_SIZE,
    CONF_VIDEO_PROFILE_NAMES,
    DEFAULT_AUDIO_CODEC,
    DEFAULT_AUDIO_PACKET_SIZE,
    DEFAULT_MAX_FPS,
    DEFAULT_MAX_HEIGHT,
    DEFAULT_MAX_WIDTH,
    DEFAULT_STREAM_COUNT,
    DEFAULT_SUPPORT_AUDIO,
    DEFAULT_VIDEO_CODEC,
    DEFAULT_VIDEO_PACKET_SIZE,
    DEFAULT_VIDEO_PROFILE_NAMES,
    SERV_MOTION_SENSOR,
)
from .doorbell import HomeDoorbellAccessory
from .util import state_changed_event_is_same_state

_LOGGER = logging.getLogger(__name__)


SLOW_RESOLUTIONS = [
    (320, 180, 15),
    (320, 240, 15),
]

RESOLUTIONS = [
    (320, 180),
    (320, 240),
    (480, 270),
    (480, 360),
    (640, 360),
    (640, 480),
    (1024, 576),
    (1024, 768),
    (1280, 720),
    (1280, 960),
    (1920, 1080),
    (1600, 1200),
]

PROCESS_WATCH_INTERVAL = timedelta(seconds=5)
STREAM_PROCESS = "stream_process"
STREAM_LOGGER = "stream_logger"
STREAM_WATCHER = "stream_watcher"
SESSION_ID = "session_id"

CONFIG_DEFAULTS = {
    CONF_SUPPORT_AUDIO: DEFAULT_SUPPORT_AUDIO,
    CONF_MAX_WIDTH: DEFAULT_MAX_WIDTH,
    CONF_MAX_HEIGHT: DEFAULT_MAX_HEIGHT,
    CONF_MAX_FPS: DEFAULT_MAX_FPS,
    CONF_AUDIO_CODEC: DEFAULT_AUDIO_CODEC,
    CONF_VIDEO_CODEC: DEFAULT_VIDEO_CODEC,
    CONF_VIDEO_PROFILE_NAMES: DEFAULT_VIDEO_PROFILE_NAMES,
    CONF_AUDIO_PACKET_SIZE: DEFAULT_AUDIO_PACKET_SIZE,
    CONF_VIDEO_PACKET_SIZE: DEFAULT_VIDEO_PACKET_SIZE,
    CONF_STREAM_COUNT: DEFAULT_STREAM_COUNT,
}


@TYPES.register("Camera")
# False-positive on pylint, not a CameraEntity
# pylint: disable-next=hass-enforce-class-module
class Camera(HomeDoorbellAccessory, PyhapCamera):  # type: ignore[misc]
    """Generate a Camera accessory."""

    def __init__(
        self,
        hass: HomeAssistant,
        driver: HomeDriver,
        name: str,
        entity_id: str,
        aid: int,
        config: dict[str, Any],
    ) -> None:
        """Initialize a Camera accessory object."""
        for config_key, conf in CONFIG_DEFAULTS.items():
            if config_key not in config:
                config[config_key] = conf

        max_fps = config[CONF_MAX_FPS]
        max_width = config[CONF_MAX_WIDTH]
        max_height = config[CONF_MAX_HEIGHT]
        resolutions = [
            (w, h, fps)
            for w, h, fps in SLOW_RESOLUTIONS
            if w <= max_width and h <= max_height and fps < max_fps
        ] + [
            (w, h, max_fps)
            for w, h in RESOLUTIONS
            if w <= max_width and h <= max_height
        ]

        video_options = {
            "codec": {
                "profiles": [
                    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["BASELINE"],
                    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["MAIN"],
                    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES["HIGH"],
                ],
                "levels": [
                    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE3_1"],
                    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE3_2"],
                    VIDEO_CODEC_PARAM_LEVEL_TYPES["TYPE4_0"],
                ],
            },
            "resolutions": resolutions,
        }
        audio_options = {
            "codecs": [
                {"type": "OPUS", "samplerate": 24},
                {"type": "OPUS", "samplerate": 16},
            ]
        }

        stream_address = config.get(CONF_STREAM_ADDRESS, driver.state.address)

        options = {
            "video": video_options,
            "audio": audio_options,
            "address": stream_address,
            "srtp": True,
            "stream_count": config[CONF_STREAM_COUNT],
        }

        super().__init__(
            hass,
            driver,
            name,
            entity_id,
            aid,
            config,
            category=CATEGORY_CAMERA,
            options=options,
        )

        self._char_motion_detected = None
        self.linked_motion_sensor: str | None = self.config.get(
            CONF_LINKED_MOTION_SENSOR
        )
        self.motion_is_event = False
        if linked_motion_sensor := self.linked_motion_sensor:
            self.motion_is_event = linked_motion_sensor.startswith("event.")
            if state := self.hass.states.get(linked_motion_sensor):
                serv_motion = self.add_preload_service(SERV_MOTION_SENSOR)
                self._char_motion_detected = serv_motion.configure_char(
                    CHAR_MOTION_DETECTED, value=False
                )
                self._async_update_motion_state(None, state)

    @pyhap_callback  # type: ignore[untyped-decorator]
    @callback
    def run(self) -> None:
        """Handle accessory driver started event.

        Run inside the Home Assistant event loop.
        """
        if self._char_motion_detected:
            assert self.linked_motion_sensor
            self._subscriptions.append(
                async_track_state_change_event(
                    self.hass,
                    self.linked_motion_sensor,
                    self._async_update_motion_state_event,
                    job_type=HassJobType.Callback,
                )
            )

        super().run()

    @callback
    def _async_update_motion_state_event(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle state change event listener callback."""
        if not state_changed_event_is_same_state(event) and (
            new_state := event.data["new_state"]
        ):
            self._async_update_motion_state(event.data["old_state"], new_state)

    @callback
    def _async_update_motion_state(
        self, old_state: State | None, new_state: State
    ) -> None:
        """Handle link motion sensor state change to update HomeKit value."""
        state = new_state.state
        char = self._char_motion_detected
        assert char is not None
        if self.motion_is_event:
            if (
                old_state is None
                or old_state.state == STATE_UNAVAILABLE
                or state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            ):
                return
            _LOGGER.debug(
                "%s: Set linked motion %s sensor to True/False",
                self.entity_id,
                self.linked_motion_sensor,
            )
            char.set_value(True)
            char.set_value(False)
            return

        detected = state == STATE_ON
        if char.value == detected:
            return

        char.set_value(detected)
        _LOGGER.debug(
            "%s: Set linked motion %s sensor to %d",
            self.entity_id,
            self.linked_motion_sensor,
            detected,
        )

    @callback
    def async_update_state(self, new_state: State | None) -> None:
        """Handle state change to update HomeKit value."""

    async def _async_get_stream_source(self) -> str | None:
        """Find the camera stream source url."""
        stream_source: str | None = self.config.get(CONF_STREAM_SOURCE)
        if stream_source:
            return stream_source
        try:
            stream_source = await camera.async_get_stream_source(
                self.hass, self.entity_id
            )
        except Exception:
            _LOGGER.exception(
                "Failed to get stream source - this could be a transient error or your"
                " camera might not be compatible with HomeKit yet"
            )
        return stream_source

    def _parse_stream_source(self, raw_source: str) -> tuple[str, dict[str, str]]:
        """Parse stream source into URL and FFmpeg input options.

        The stream_source config value may include FFmpeg input flags
        (e.g. "-rtsp_transport tcp -i rtsp://..."). This extracts the
        URL and converts flags to PyAV input options.
        """
        if "-i " not in raw_source:
            return raw_source, {}

        # Split on -i to separate input options from URL
        parts = raw_source.rsplit("-i ", maxsplit=1)
        url = parts[1].strip().split()[0]

        # Parse input options from the prefix (e.g. "-rtsp_transport tcp")
        input_options: dict[str, str] = {}
        tokens = parts[0].strip().split()
        i = 0
        while i < len(tokens):
            if tokens[i].startswith("-") and i + 1 < len(tokens):
                key = tokens[i].lstrip("-")
                input_options[key] = tokens[i + 1]
                i += 2
            else:
                i += 1

        return url, input_options

    async def start_stream(
        self, session_info: dict[str, Any], stream_config: dict[str, Any]
    ) -> bool:
        """Start a new stream with the given configuration."""
        _LOGGER.debug(
            "[%s] Starting stream with the following parameters: %s",
            session_info["id"],
            stream_config,
        )
        if not (raw_source := await self._async_get_stream_source()):
            _LOGGER.error("Camera has no stream source")
            return False

        source_url, input_options = self._parse_stream_source(raw_source)

        # Determine video profile name from the negotiated profile ID
        video_profile = self.config[CONF_VIDEO_PROFILE_NAMES][
            int.from_bytes(stream_config["v_profile_id"], byteorder="big")
        ]

        # Build the config for the PyAV streamer subprocess
        streamer_config: dict[str, Any] = {
            "source": source_url,
            "address": stream_config["address"],
            "input_options": input_options,
            "video": {
                "port": stream_config["v_port"],
                "srtp_key": stream_config["v_srtp_key"],
                "ssrc": stream_config["v_ssrc"],
                "payload_type": 99,
                "pkt_size": self.config[CONF_VIDEO_PACKET_SIZE],
                "codec": self.config[CONF_VIDEO_CODEC],
                "profile": video_profile,
                "max_bitrate": stream_config["v_max_bitrate"],
                "fps": stream_config["fps"],
                "width": stream_config["width"],
                "height": stream_config["height"],
            },
        }

        if self.config[CONF_SUPPORT_AUDIO]:
            streamer_config["audio"] = {
                "port": stream_config["a_port"],
                "srtp_key": stream_config["a_srtp_key"],
                "ssrc": stream_config["a_ssrc"],
                "payload_type": stream_config.get("a_payload_type", 110),
                "pkt_size": self.config[CONF_AUDIO_PACKET_SIZE],
                "codec": self.config[CONF_AUDIO_CODEC],
                "sample_rate": stream_config["a_sample_rate"],
                "packet_time": stream_config.get("a_packet_time", 20),
                "max_bitrate": stream_config["a_max_bitrate"],
            }

        _LOGGER.debug(
            "[%s] Launching PyAV streamer: source=%s video_codec=%s audio=%s",
            session_info["id"],
            source_url,
            self.config[CONF_VIDEO_CODEC],
            "enabled" if self.config[CONF_SUPPORT_AUDIO] else "disabled",
        )

        stream_process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "homeassistant.components.homekit.audio_streamer",
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
        )

        session_info[STREAM_PROCESS] = stream_process

        _LOGGER.debug(
            "[%s] Started stream process - PID %d",
            session_info["id"],
            stream_process.pid,
        )

        # Send config via stdin (one JSON line), keep stdin open
        # for liveness signaling (close = stop)
        assert stream_process.stdin is not None
        config_line = json.dumps(streamer_config) + "\n"
        stream_process.stdin.write(config_line.encode())
        await stream_process.stdin.drain()

        # Log stderr from the streamer process
        if stream_process.stderr:
            session_info[STREAM_LOGGER] = create_eager_task(
                self._async_log_stream_stderr(session_info["id"], stream_process.stderr)
            )

        # Watch the process periodically
        async def watch_session(_: Any) -> None:
            await self._async_process_watch(session_info["id"])

        session_info[STREAM_WATCHER] = async_track_time_interval(
            self.hass,
            watch_session,
            PROCESS_WATCH_INTERVAL,
        )

        return await self._async_process_watch(session_info["id"])

    async def _async_log_stream_stderr(
        self, session_id: str, stderr: asyncio.StreamReader
    ) -> None:
        """Log stderr output from the streamer subprocess."""
        while True:
            line = await stderr.readline()
            if line == b"":
                return
            _LOGGER.debug(
                "[%s] streamer: %s",
                session_id,
                line.rstrip().decode("utf-8", errors="replace"),
            )

    async def _async_process_watch(self, session_id: str) -> bool:
        """Check to make sure the streamer is still running."""
        stream_process: asyncio.subprocess.Process | None = self.sessions[
            session_id
        ].get(STREAM_PROCESS)
        if stream_process is None:
            return False

        if stream_process.returncode is None:
            # Still running
            return True

        _LOGGER.warning(
            "Streaming process ended unexpectedly - PID %d (rc=%d)",
            stream_process.pid,
            stream_process.returncode,
        )
        self._async_stop_process_watch(session_id)
        self.set_streaming_available(self.sessions[session_id]["stream_idx"])
        return False

    @callback
    def _async_stop_process_watch(self, session_id: str) -> None:
        """Clean up a streaming session watcher."""
        if STREAM_WATCHER not in self.sessions[session_id]:
            return
        self.sessions[session_id].pop(STREAM_WATCHER)()
        if logger := self.sessions[session_id].pop(STREAM_LOGGER, None):
            logger.cancel()

    @callback
    def async_stop(self) -> None:
        """Stop any streams when the accessory is stopped."""
        for session_info in self.sessions.values():
            self.hass.async_create_background_task(
                self.stop_stream(session_info), "homekit.camera-stop-stream"
            )
        super().async_stop()

    async def stop_stream(self, session_info: dict[str, Any]) -> None:
        """Stop the stream for the given session."""
        session_id = session_info["id"]
        stream_process: asyncio.subprocess.Process | None = session_info.pop(
            STREAM_PROCESS, None
        )
        if stream_process is None:
            _LOGGER.debug("No stream for session ID %s", session_id)
            return

        self._async_stop_process_watch(session_id)

        if stream_process.returncode is not None:
            _LOGGER.debug(
                "[%s] Stream already stopped (rc=%d)",
                session_id,
                stream_process.returncode,
            )
            return

        _LOGGER.debug("[%s] Stopping stream - PID %d", session_id, stream_process.pid)

        # Close stdin to signal the child to stop gracefully
        if stream_process.stdin:
            stream_process.stdin.close()

        # Give it time to exit, then escalate
        try:
            await asyncio.wait_for(stream_process.wait(), timeout=3.0)
        except TimeoutError:
            _LOGGER.debug("[%s] Stream did not stop, terminating", session_id)
            stream_process.terminate()
            try:
                await asyncio.wait_for(stream_process.wait(), timeout=2.0)
            except TimeoutError:
                _LOGGER.warning("[%s] Stream did not terminate, killing", session_id)
                stream_process.kill()

    async def reconfigure_stream(
        self, session_info: dict[str, Any], stream_config: dict[str, Any]
    ) -> bool:
        """Reconfigure the stream so that it uses the given ``stream_config``."""
        return True

    async def async_get_snapshot(self, image_size: dict[str, int]) -> bytes:
        """Return a jpeg of a snapshot from the camera."""
        image = await camera.async_get_image(
            self.hass,
            self.entity_id,
            width=image_size["image-width"],
            height=image_size["image-height"],
        )
        return image.content
