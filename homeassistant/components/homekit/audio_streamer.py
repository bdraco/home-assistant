"""Standalone audio streamer for HomeKit cameras using PyAV.

This module runs as a separate process to stream audio from an RTSP source
to a HomeKit client via SRTP. It uses PyAV (libav) to decode, resample, and
re-encode audio as Opus with the exact frame duration requested by the
HomeKit client (a_packet_time), fixing choppy audio caused by frame duration
mismatch.

Background:
  FFmpeg always generates 20ms Opus frames, but iOS HomeKit clients may
  request different durations (20ms on WiFi, 60ms on cellular). Without
  matching the requested duration, audio is choppy or silent. See:
  https://github.com/AlexxIT/go2rtc/issues/667
  https://github.com/AlexxIT/go2rtc/pull/843

Usage:
  python -m homeassistant.components.homekit.audio_streamer <json_config>
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import json
import logging
import signal
import sys
import threading
import time
from typing import Any

import av
from av.audio.resampler import AudioResampler  # pylint: disable=no-name-in-module
from av.audio.stream import AudioStream

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s [homekit.audio] %(message)s",
    stream=sys.stderr,
)
_LOGGER = logging.getLogger(__name__)

# Input timeout for opening RTSP source (seconds)
INPUT_TIMEOUT = 10.0


@dataclass(slots=True, frozen=True)
class StreamConfig:
    """Configuration for a HomeKit audio stream."""

    source: str
    address: str
    port: int
    srtp_key: str
    ssrc: int
    sample_rate_khz: int  # 8, 16, or 24
    packet_time_ms: int  # 20 or 60
    max_bitrate_kbps: int
    payload_type: int  # typically 110
    pkt_size: int

    @property
    def sample_rate(self) -> int:
        """Return sample rate in Hz."""
        return self.sample_rate_khz * 1000

    @property
    def frame_size(self) -> int:
        """Return Opus frame size in samples for the requested packet_time."""
        return self.packet_time_ms * self.sample_rate_khz

    @property
    def srtp_url(self) -> str:
        """Return SRTP output URL."""
        return (
            f"srtp://{self.address}:{self.port}"
            f"?rtcpport={self.port}"
            f"&localrtpport={self.port}"
            f"&pkt_size={self.pkt_size}"
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StreamConfig:
        """Create from a dictionary."""
        return cls(
            source=data["source"],
            address=data["address"],
            port=int(data["port"]),
            srtp_key=data["srtp_key"],
            ssrc=int(data["ssrc"]),
            sample_rate_khz=int(data["sample_rate"]),
            packet_time_ms=int(data["packet_time"]),
            max_bitrate_kbps=int(data["max_bitrate"]),
            payload_type=int(data.get("payload_type", 110)),
            pkt_size=int(data.get("pkt_size", 188)),
        )


def stream_audio(config: StreamConfig, stop_event: threading.Event) -> None:
    """Stream audio from source to HomeKit client via SRTP.

    This function:
    1. Opens the RTSP source and finds the audio stream
    2. Creates an SRTP output with Opus encoding at the exact frame
       duration requested by the HomeKit client
    3. Decodes, resamples, and re-encodes audio frames
    4. Paces output to real-time to avoid flooding UDP buffers
    """
    _LOGGER.info(
        "Starting audio stream: source=%s target=%s rate=%dkHz packet_time=%dms",
        config.source,
        config.srtp_url,
        config.sample_rate_khz,
        config.packet_time_ms,
    )

    frame_size = config.frame_size
    _LOGGER.debug(
        "Opus frame_size=%d samples (%dms at %dHz)",
        frame_size,
        config.packet_time_ms,
        config.sample_rate,
    )

    # Open the input source (RTSP camera stream)
    try:
        input_container = av.open(
            config.source,
            timeout=(INPUT_TIMEOUT, INPUT_TIMEOUT),
        )
    except av.FFmpegError:
        _LOGGER.exception("Failed to open source %s", config.source)
        return

    start_time = time.monotonic()
    samples_sent = 0
    packets_sent = 0

    with input_container:
        if not input_container.streams.audio:
            _LOGGER.error("No audio stream found in source")
            return

        input_stream = input_container.streams.audio[0]
        _LOGGER.info(
            "Input audio: codec=%s rate=%d channels=%d",
            input_stream.codec_context.name,
            input_stream.codec_context.sample_rate,
            input_stream.codec_context.channels,
        )

        # Open SRTP output
        try:
            output_container = av.open(
                config.srtp_url,
                "w",
                format="rtp",
                options={
                    "srtp_out_suite": "AES_CM_128_HMAC_SHA1_80",
                    "srtp_out_params": config.srtp_key,
                },
                timeout=(5.0, None),
            )
        except av.FFmpegError:
            _LOGGER.exception("Failed to open SRTP output %s", config.srtp_url)
            return

        with output_container:
            # Add Opus output stream with exact frame duration
            output_stream: AudioStream = output_container.add_stream(
                "libopus",
                rate=config.sample_rate,
                options={
                    "application": "lowdelay",
                    "frame_duration": str(config.packet_time_ms),
                },
            )
            output_stream.bit_rate = config.max_bitrate_kbps * 1000
            output_stream.layout = "mono"

            # Resampler: convert input audio to target format
            resampler = AudioResampler(
                format="s16",
                layout="mono",
                rate=config.sample_rate,
            )

            _LOGGER.info("Streaming audio")

            try:
                for frame in input_container.decode(input_stream):
                    if stop_event.is_set():
                        _LOGGER.debug("Stop requested, ending stream")
                        break

                    for resampled in resampler.resample(frame):
                        for packet in output_stream.encode(resampled):
                            output_container.mux(packet)
                            packets_sent += 1

                        # Pace output to real-time to avoid
                        # flooding UDP buffers (no flow control)
                        samples_sent += resampled.samples
                        target_time = start_time + (samples_sent / config.sample_rate)
                        sleep_time = target_time - time.monotonic()
                        if sleep_time > 0 and stop_event.wait(sleep_time):
                            break

                # Flush encoder
                if not stop_event.is_set():
                    for packet in output_stream.encode(None):
                        output_container.mux(packet)
                        packets_sent += 1

            except av.FFmpegError:
                _LOGGER.exception("Streaming error")

    elapsed = time.monotonic() - start_time
    _LOGGER.info("Stream ended: %d packets sent in %.1fs", packets_sent, elapsed)


def main() -> None:
    """Entry point for the audio streamer subprocess."""
    if len(sys.argv) < 2:
        _LOGGER.error("Usage: %s <json_config>", sys.argv[0])
        sys.exit(1)

    config_data = json.loads(sys.argv[1])
    config = StreamConfig.from_dict(config_data)

    stop_event = threading.Event()

    def handle_signal(signum: int, _frame: Any) -> None:
        _LOGGER.info("Received signal %d, stopping", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Monitor stdin - when parent closes it, we should exit
    def watch_stdin() -> None:
        with contextlib.suppress(OSError):
            sys.stdin.read()
        _LOGGER.info("Parent closed stdin, stopping")
        stop_event.set()

    stdin_thread = threading.Thread(target=watch_stdin, daemon=True)
    stdin_thread.start()

    stream_audio(config, stop_event)


if __name__ == "__main__":
    main()
