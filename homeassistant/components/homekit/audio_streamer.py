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
  python -m homeassistant.components.homekit.audio_streamer

  Reads JSON config from stdin (one line), then keeps stdin open.
  When stdin closes (parent died) or SIGTERM is received, stops gracefully.
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
from urllib.parse import urlparse

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


def _format_address_for_url(address: str) -> str:
    """Wrap IPv6 addresses in brackets for URL use."""
    parsed = urlparse(f"//{address}")
    if ":" in address and parsed.hostname != address:
        # Already has brackets or is not a plain IPv6 address
        return address
    if ":" in address:
        return f"[{address}]"
    return address


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
    def srtp_url(self) -> str:
        """Return SRTP output URL."""
        addr = _format_address_for_url(self.address)
        return (
            f"srtp://{addr}:{self.port}"
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

    Note: This opens a separate RTSP connection to the camera for audio.
    Most cameras support at least 2 concurrent streams. A future
    optimization could pipe audio from FFmpeg to avoid the extra connection.
    """
    _LOGGER.info(
        "Starting audio stream: source=%s target=%s rate=%dkHz packet_time=%dms",
        config.source,
        config.srtp_url,
        config.sample_rate_khz,
        config.packet_time_ms,
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

        # Open SRTP output with SSRC and payload_type set on the RTP muxer
        try:
            output_container = av.open(
                config.srtp_url,
                "w",
                format="rtp",
                options={
                    "srtp_out_suite": "AES_CM_128_HMAC_SHA1_80",
                    "srtp_out_params": config.srtp_key,
                    "ssrc": str(config.ssrc),
                    "payload_type": str(config.payload_type),
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

            # Set start_time after all setup is complete so pacing
            # is not skewed by connection/setup latency
            start_time = time.monotonic()

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
    """Entry point for the audio streamer subprocess.

    Reads JSON config from stdin (first line), then keeps stdin open.
    Stops when stdin is closed (parent died) or SIGTERM is received.
    """
    # Read config from stdin to avoid exposing SRTP keys in process list
    config_line = sys.stdin.readline()
    if not config_line:
        _LOGGER.error("No config received on stdin")
        sys.exit(1)

    config_data = json.loads(config_line)
    config = StreamConfig.from_dict(config_data)

    stop_event = threading.Event()

    def handle_signal(signum: int, _frame: Any) -> None:
        _LOGGER.info("Received signal %d, stopping", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Monitor stdin - when parent closes it, we should exit.
    # After reading the config line above, stdin stays open as a
    # liveness signal. When the parent closes it, we stop.
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
