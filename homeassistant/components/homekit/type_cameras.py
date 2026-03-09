"""Class to hold all camera accessories."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import logging
import subprocess
import sys
from typing import Any

from haffmpeg.core import FFMPEG_STDERR, HAFFmpeg
from pyhap.camera import (
    VIDEO_CODEC_PARAM_LEVEL_TYPES,
    VIDEO_CODEC_PARAM_PROFILE_ID_TYPES,
    Camera as PyhapCamera,
)
from pyhap.const import CATEGORY_CAMERA
from pyhap.util import callback as pyhap_callback

from homeassistant.components import camera
from homeassistant.components.ffmpeg import get_ffmpeg_manager
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
    AUDIO_CODEC_OPUS,
    CHAR_MOTION_DETECTED,
    CONF_AUDIO_CODEC,
    CONF_AUDIO_MAP,
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
    CONF_VIDEO_MAP,
    CONF_VIDEO_PACKET_SIZE,
    CONF_VIDEO_PROFILE_NAMES,
    DEFAULT_AUDIO_CODEC,
    DEFAULT_AUDIO_MAP,
    DEFAULT_AUDIO_PACKET_SIZE,
    DEFAULT_MAX_FPS,
    DEFAULT_MAX_HEIGHT,
    DEFAULT_MAX_WIDTH,
    DEFAULT_STREAM_COUNT,
    DEFAULT_SUPPORT_AUDIO,
    DEFAULT_VIDEO_CODEC,
    DEFAULT_VIDEO_MAP,
    DEFAULT_VIDEO_PACKET_SIZE,
    DEFAULT_VIDEO_PROFILE_NAMES,
    SERV_MOTION_SENSOR,
)
from .doorbell import HomeDoorbellAccessory
from .util import pid_is_alive, state_changed_event_is_same_state

_LOGGER = logging.getLogger(__name__)


VIDEO_OUTPUT = (
    "-map {v_map} -an "
    "-c:v {v_codec} "
    "{v_profile}"
    "-tune zerolatency -pix_fmt yuv420p "
    "-r {fps} "
    "-b:v {v_max_bitrate}k -bufsize {v_bufsize}k -maxrate {v_max_bitrate}k "
    "-payload_type 99 "
    "-ssrc {v_ssrc} -f rtp "
    "-srtp_out_suite AES_CM_128_HMAC_SHA1_80 -srtp_out_params {v_srtp_key} "
    "srtp://{address}:{v_port}?rtcpport={v_port}&"
    "localrtpport={v_port}&pkt_size={v_pkt_size}"
)

AUDIO_OUTPUT = (
    "-map {a_map} -vn "
    "-c:a {a_encoder} "
    "{a_application}"
    "-ac 1 -ar {a_sample_rate}k "
    "-b:a {a_max_bitrate}k -bufsize {a_bufsize}k "
    "-payload_type 110 "
    "-ssrc {a_ssrc} -f rtp "
    "-srtp_out_suite AES_CM_128_HMAC_SHA1_80 -srtp_out_params {a_srtp_key} "
    "srtp://{address}:{a_port}?rtcpport={a_port}&"
    "localrtpport={a_port}&pkt_size={a_pkt_size}"
)

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

FFMPEG_WATCH_INTERVAL = timedelta(seconds=5)
FFMPEG_LOGGER = "ffmpeg_logger"
FFMPEG_WATCHER = "ffmpeg_watcher"
FFMPEG_PID = "ffmpeg_pid"
AUDIO_STREAM_PROCESS = "audio_stream_process"
AUDIO_LOGGER = "audio_logger"
SESSION_ID = "session_id"

CONFIG_DEFAULTS = {
    CONF_SUPPORT_AUDIO: DEFAULT_SUPPORT_AUDIO,
    CONF_MAX_WIDTH: DEFAULT_MAX_WIDTH,
    CONF_MAX_HEIGHT: DEFAULT_MAX_HEIGHT,
    CONF_MAX_FPS: DEFAULT_MAX_FPS,
    CONF_AUDIO_CODEC: DEFAULT_AUDIO_CODEC,
    CONF_AUDIO_MAP: DEFAULT_AUDIO_MAP,
    CONF_VIDEO_MAP: DEFAULT_VIDEO_MAP,
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
        self._ffmpeg = get_ffmpeg_manager(hass)
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

    def _get_audio_stream_source(self, raw_source: str) -> str:
        """Extract the raw stream URL from the input source.

        The stream_source config value may include FFmpeg flags
        (e.g. "-rtsp_transport tcp -i rtsp://..."). We need the
        raw URL for the PyAV audio subprocess.
        """
        if "-i " not in raw_source:
            return raw_source
        # Take the token immediately after the last -i flag
        parts = raw_source.rsplit("-i ", maxsplit=1)
        return parts[1].strip().split()[0]

    def _should_use_pyav_audio(self) -> bool:
        """Check if PyAV audio streaming should be used.

        PyAV audio streaming is used when the audio codec is Opus, which
        requires repacketization to match the HomeKit client's requested
        frame duration (a_packet_time).
        """
        return bool(
            self.config[CONF_SUPPORT_AUDIO]
            and self.config[CONF_AUDIO_CODEC] == AUDIO_CODEC_OPUS
        )

    async def _async_start_audio_stream(
        self,
        session_info: dict[str, Any],
        stream_config: dict[str, Any],
        raw_source: str,
    ) -> None:
        """Start the PyAV audio streamer subprocess.

        Launches a separate Python process that handles audio transcoding
        with correct Opus frame duration matching the HomeKit client's
        a_packet_time request. This fixes choppy audio caused by FFmpeg
        always generating 20ms Opus frames regardless of what the client
        requested.

        Config is passed via stdin (not CLI args) to avoid exposing
        SRTP keys in the process list.
        """
        audio_config = {
            "source": raw_source,
            "address": stream_config["address"],
            "port": stream_config["a_port"],
            "srtp_key": stream_config["a_srtp_key"],
            "ssrc": stream_config["a_ssrc"],
            "sample_rate": stream_config["a_sample_rate"],
            "packet_time": stream_config.get("a_packet_time", 20),
            "max_bitrate": stream_config["a_max_bitrate"],
            "payload_type": stream_config.get("a_payload_type", 110),
            "pkt_size": self.config[CONF_AUDIO_PACKET_SIZE],
        }

        _LOGGER.debug(
            "[%s] Starting PyAV audio stream with config: %s",
            session_info["id"],
            {k: v for k, v in audio_config.items() if k != "srtp_key"},
        )

        audio_process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "homeassistant.components.homekit.audio_streamer",
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
        )

        session_info[AUDIO_STREAM_PROCESS] = audio_process

        _LOGGER.debug(
            "[%s] Started audio stream process - PID %d",
            session_info["id"],
            audio_process.pid,
        )

        # Send config via stdin (one JSON line), keep stdin open
        # for liveness signaling (close = stop)
        assert audio_process.stdin is not None
        config_line = json.dumps(audio_config) + "\n"
        audio_process.stdin.write(config_line.encode())
        await audio_process.stdin.drain()

        # Log stderr from the audio process
        if audio_process.stderr:
            session_info[AUDIO_LOGGER] = create_eager_task(
                self._async_log_audio_stderr(session_info["id"], audio_process.stderr)
            )

    async def _async_log_audio_stderr(
        self, session_id: str, stderr: asyncio.StreamReader
    ) -> None:
        """Log stderr output from the audio streamer subprocess."""
        while True:
            line = await stderr.readline()
            if line == b"":
                return
            _LOGGER.debug(
                "[%s] audio: %s",
                session_id,
                line.rstrip().decode("utf-8", errors="replace"),
            )

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

        use_pyav_audio = self._should_use_pyav_audio()

        input_source = raw_source
        if "-i " not in input_source:
            input_source = "-i " + input_source
        video_profile = ""
        if self.config[CONF_VIDEO_CODEC] != "copy":
            video_profile = (
                "-profile:v "
                + self.config[CONF_VIDEO_PROFILE_NAMES][
                    int.from_bytes(stream_config["v_profile_id"], byteorder="big")
                ]
                + " "
            )
        audio_application = ""
        if self.config[CONF_AUDIO_CODEC] == "libopus":
            audio_application = "-application lowdelay "
        output_vars = stream_config.copy()
        output_vars.update(
            {
                "v_profile": video_profile,
                "v_bufsize": stream_config["v_max_bitrate"] * 4,
                "v_map": self.config[CONF_VIDEO_MAP],
                "v_pkt_size": self.config[CONF_VIDEO_PACKET_SIZE],
                "v_codec": self.config[CONF_VIDEO_CODEC],
                "a_bufsize": stream_config["a_max_bitrate"] * 4,
                "a_map": self.config[CONF_AUDIO_MAP],
                "a_pkt_size": self.config[CONF_AUDIO_PACKET_SIZE],
                "a_encoder": self.config[CONF_AUDIO_CODEC],
                "a_application": audio_application,
            }
        )
        output = VIDEO_OUTPUT.format(**output_vars)
        if self.config[CONF_SUPPORT_AUDIO] and not use_pyav_audio:
            # Use FFmpeg for audio when not using PyAV audio streamer
            output = output + " " + AUDIO_OUTPUT.format(**output_vars)
        _LOGGER.debug("FFmpeg output settings: %s", output)
        stream = HAFFmpeg(self._ffmpeg.binary)
        opened = await stream.open(
            cmd=[],
            input_source=input_source,
            output=output,
            extra_cmd="-hide_banner -nostats",
            stderr_pipe=True,
            stdout_pipe=False,
        )
        if not opened:
            _LOGGER.error("Failed to open ffmpeg stream")
            return False

        _LOGGER.debug(
            "[%s] Started stream process - PID %d",
            session_info["id"],
            stream.process.pid,
        )

        session_info["stream"] = stream
        session_info[FFMPEG_PID] = stream.process.pid

        stderr_reader = await stream.get_reader(source=FFMPEG_STDERR)

        async def watch_session(_: Any) -> None:
            await self._async_ffmpeg_watch(session_info["id"])

        session_info[FFMPEG_LOGGER] = create_eager_task(
            self._async_log_stderr_stream(stderr_reader)
        )
        session_info[FFMPEG_WATCHER] = async_track_time_interval(
            self.hass,
            watch_session,
            FFMPEG_WATCH_INTERVAL,
        )

        # Start PyAV audio streamer as a separate process
        if use_pyav_audio:
            audio_source = self._get_audio_stream_source(raw_source)
            await self._async_start_audio_stream(
                session_info, stream_config, audio_source
            )

        return await self._async_ffmpeg_watch(session_info["id"])

    async def _async_log_stderr_stream(
        self, stderr_reader: asyncio.StreamReader
    ) -> None:
        """Log output from ffmpeg."""
        _LOGGER.debug("%s: ffmpeg: started", self.display_name)
        while True:
            line = await stderr_reader.readline()
            if line == b"":
                return

            _LOGGER.debug("%s: ffmpeg: %s", self.display_name, line.rstrip())

    async def _async_ffmpeg_watch(self, session_id: str) -> bool:
        """Check to make sure ffmpeg is still running and cleanup if not."""
        ffmpeg_pid = self.sessions[session_id][FFMPEG_PID]
        if pid_is_alive(ffmpeg_pid):
            return True

        _LOGGER.warning("Streaming process ended unexpectedly - PID %d", ffmpeg_pid)
        self._async_stop_ffmpeg_watch(session_id)
        self.set_streaming_available(self.sessions[session_id]["stream_idx"])
        return False

    @callback
    def _async_stop_ffmpeg_watch(self, session_id: str) -> None:
        """Cleanup a streaming session after stopping."""
        if FFMPEG_WATCHER not in self.sessions[session_id]:
            return
        self.sessions[session_id].pop(FFMPEG_WATCHER)()
        self.sessions[session_id].pop(FFMPEG_LOGGER).cancel()

    @callback
    def async_stop(self) -> None:
        """Stop any streams when the accessory is stopped."""
        for session_info in self.sessions.values():
            self.hass.async_create_background_task(
                self.stop_stream(session_info), "homekit.camera-stop-stream"
            )
        super().async_stop()

    async def _async_stop_audio_stream(self, session_info: dict[str, Any]) -> None:
        """Stop the PyAV audio streamer subprocess."""
        audio_process: asyncio.subprocess.Process | None = session_info.pop(
            AUDIO_STREAM_PROCESS, None
        )
        if audio_process is None:
            return

        session_id = session_info["id"]

        # Cancel the audio logger task
        if audio_logger := session_info.pop(AUDIO_LOGGER, None):
            audio_logger.cancel()

        if audio_process.returncode is not None:
            _LOGGER.debug(
                "[%s] Audio stream already stopped (rc=%d)",
                session_id,
                audio_process.returncode,
            )
            return

        _LOGGER.debug(
            "[%s] Stopping audio stream - PID %d", session_id, audio_process.pid
        )

        # Close stdin to signal the child to stop
        if audio_process.stdin:
            audio_process.stdin.close()

        # Give it a moment to exit gracefully, then terminate
        try:
            await asyncio.wait_for(audio_process.wait(), timeout=3.0)
        except TimeoutError:
            _LOGGER.debug("[%s] Audio stream did not stop, terminating", session_id)
            audio_process.terminate()
            try:
                await asyncio.wait_for(audio_process.wait(), timeout=2.0)
            except TimeoutError:
                _LOGGER.warning(
                    "[%s] Audio stream did not terminate, killing", session_id
                )
                audio_process.kill()

    async def stop_stream(self, session_info: dict[str, Any]) -> None:
        """Stop the stream for the given ``session_id``."""
        session_id = session_info["id"]
        if not (stream := session_info.get("stream")):
            _LOGGER.debug("No stream for session ID %s", session_id)
            return

        self._async_stop_ffmpeg_watch(session_id)

        # Stop the audio streamer subprocess if running
        await self._async_stop_audio_stream(session_info)

        if not pid_is_alive(stream.process.pid):
            _LOGGER.warning("[%s] Stream already stopped", session_id)
            return

        for shutdown_method in ("close", "kill"):
            _LOGGER.debug("[%s] %s stream", session_id, shutdown_method)
            try:
                await getattr(stream, shutdown_method)()
            except Exception:
                _LOGGER.exception(
                    "[%s] Failed to %s stream", session_id, shutdown_method
                )
            else:
                return

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
