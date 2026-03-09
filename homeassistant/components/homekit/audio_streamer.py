"""Standalone A/V streamer for HomeKit cameras using PyAV.

This module runs as a separate process to stream video and audio from
an RTSP source to a HomeKit client via SRTP. It replaces the FFmpeg
subprocess approach, giving full control over Opus frame duration to
match the HomeKit client's a_packet_time request.

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
from dataclasses import dataclass, field
import json
import logging
import signal
import sys
import threading
import time
from typing import Any
from urllib.parse import quote

import av
from av.audio.resampler import AudioResampler  # pylint: disable=no-name-in-module
from av.audio.stream import AudioStream

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s [homekit.av] %(message)s",
    stream=sys.stderr,
)
_LOGGER = logging.getLogger(__name__)

# Input timeout for opening RTSP source (seconds)
INPUT_TIMEOUT = 10.0

# Video codec name that means passthrough (no re-encoding)
CODEC_COPY = "copy"


def _format_address_for_url(address: str) -> str:
    """Wrap IPv6 addresses in brackets for URL use."""
    if ":" in address and not address.startswith("["):
        return f"[{address}]"
    return address


def _build_srtp_url(address: str, port: int, pkt_size: int, srtp_key: str) -> str:
    """Build an SRTP output URL with encryption params in the query string.

    The srtp_out_suite and srtp_out_params must be in the URL because
    they are protocol-level options consumed by FFmpeg's SRTP protocol
    handler, not muxer options. Passing them via av.open(options=...)
    sends them to the RTP muxer which ignores them.
    """
    addr = _format_address_for_url(address)
    return (
        f"srtp://{addr}:{port}?rtcpport={port}"
        f"&pkt_size={pkt_size}"
        f"&srtp_out_suite=AES_CM_128_HMAC_SHA1_80"
        f"&srtp_out_params={quote(srtp_key, safe='')}"
    )


@dataclass(slots=True, frozen=True)
class VideoConfig:
    """Video stream configuration."""

    port: int
    srtp_key: str
    ssrc: int
    payload_type: int
    pkt_size: int
    codec: str  # "copy", "libx264", "h264_omx", etc.
    profile: str  # "baseline", "main", "high"
    max_bitrate_kbps: int
    fps: int
    width: int
    height: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VideoConfig:
        """Create from a dictionary."""
        return cls(
            port=int(data["port"]),
            srtp_key=data["srtp_key"],
            ssrc=int(data["ssrc"]),
            payload_type=int(data.get("payload_type", 99)),
            pkt_size=int(data.get("pkt_size", 1316)),
            codec=data.get("codec", CODEC_COPY),
            profile=data.get("profile", "main"),
            max_bitrate_kbps=int(data.get("max_bitrate", 300)),
            fps=int(data.get("fps", 30)),
            width=int(data.get("width", 1920)),
            height=int(data.get("height", 1080)),
        )


@dataclass(slots=True, frozen=True)
class AudioConfig:
    """Audio stream configuration."""

    port: int
    srtp_key: str
    ssrc: int
    payload_type: int
    pkt_size: int
    codec: str  # "libopus"
    sample_rate_khz: int  # 8, 16, or 24
    packet_time_ms: int  # 20 or 60
    max_bitrate_kbps: int

    @property
    def sample_rate(self) -> int:
        """Return sample rate in Hz."""
        return self.sample_rate_khz * 1000

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioConfig:
        """Create from a dictionary."""
        return cls(
            port=int(data["port"]),
            srtp_key=data["srtp_key"],
            ssrc=int(data["ssrc"]),
            payload_type=int(data.get("payload_type", 110)),
            pkt_size=int(data.get("pkt_size", 188)),
            codec=data.get("codec", "libopus"),
            sample_rate_khz=int(data.get("sample_rate", 24)),
            packet_time_ms=int(data.get("packet_time", 20)),
            max_bitrate_kbps=int(data.get("max_bitrate", 24)),
        )


@dataclass(slots=True, frozen=True)
class StreamConfig:
    """Full stream configuration."""

    source: str
    address: str
    video: VideoConfig
    audio: AudioConfig | None = None
    # FFmpeg input options (e.g. {"rtsp_transport": "tcp"})
    input_options: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StreamConfig:
        """Create from a dictionary."""
        audio = None
        if audio_data := data.get("audio"):
            audio = AudioConfig.from_dict(audio_data)
        return cls(
            source=data["source"],
            address=data["address"],
            video=VideoConfig.from_dict(data["video"]),
            audio=audio,
            input_options=data.get("input_options", {}),
        )


def _open_srtp_output(
    address: str,
    port: int,
    pkt_size: int,
    srtp_key: str,
    ssrc: int,
    payload_type: int,
) -> av.container.OutputContainer:
    """Open an SRTP output container."""
    url = _build_srtp_url(address, port, pkt_size, srtp_key)
    _LOGGER.debug(
        "Opening SRTP output: %s ssrc=%d payload_type=%d", url, ssrc, payload_type
    )
    return av.open(
        url,
        "w",
        format="rtp",
        options={
            "ssrc": str(ssrc),
            "payload_type": str(payload_type),
        },
        timeout=(5.0, None),
    )


def _setup_video_output(
    config: StreamConfig,
    input_stream: av.stream.Stream,
) -> tuple[av.container.OutputContainer, av.stream.Stream]:
    """Set up the video SRTP output container and stream."""
    vc = config.video
    video_output = _open_srtp_output(
        config.address,
        vc.port,
        vc.pkt_size,
        vc.srtp_key,
        vc.ssrc,
        vc.payload_type,
    )

    if vc.codec == CODEC_COPY:
        # Set up output stream to remux packets without re-encoding
        _LOGGER.debug("Video copy mode: codec=%s", input_stream.codec_context.name)
        out_video = video_output.add_stream(input_stream.codec_context.name)
        out_video.width = input_stream.codec_context.width  # type: ignore[attr-defined, union-attr]
        out_video.height = input_stream.codec_context.height  # type: ignore[attr-defined, union-attr]
        if input_stream.codec_context.extradata:
            out_video.codec_context.extradata = input_stream.codec_context.extradata
        return video_output, out_video

    _LOGGER.debug(
        "Video transcode: codec=%s %dx%d @%dfps %dkbps profile=%s",
        vc.codec,
        vc.width,
        vc.height,
        vc.fps,
        vc.max_bitrate_kbps,
        vc.profile,
    )
    out_video = video_output.add_stream(vc.codec, rate=vc.fps)
    out_video.width = vc.width  # type: ignore[union-attr]
    out_video.height = vc.height  # type: ignore[union-attr]
    out_video.bit_rate = vc.max_bitrate_kbps * 1000  # type: ignore[union-attr]
    out_video.pix_fmt = "yuv420p"  # type: ignore[union-attr]
    out_video.options = {
        "tune": "zerolatency",
        "profile": vc.profile,
    }
    return video_output, out_video


def _setup_audio_output(
    config: StreamConfig,
) -> tuple[av.container.OutputContainer, AudioStream, AudioResampler]:
    """Set up the audio SRTP output container, stream, and resampler."""
    ac = config.audio
    assert ac is not None

    audio_output = _open_srtp_output(
        config.address,
        ac.port,
        ac.pkt_size,
        ac.srtp_key,
        ac.ssrc,
        ac.payload_type,
    )

    _LOGGER.debug(
        "Audio output: opus %dHz %dms %dkbps",
        ac.sample_rate,
        ac.packet_time_ms,
        ac.max_bitrate_kbps,
    )
    out_stream = audio_output.add_stream(
        "libopus",
        rate=ac.sample_rate,
        options={
            "application": "lowdelay",
            "frame_duration": str(ac.packet_time_ms),
        },
    )
    out_stream.bit_rate = ac.max_bitrate_kbps * 1000
    out_stream.layout = "mono"

    resampler = AudioResampler(
        format="s16",
        layout="mono",
        rate=ac.sample_rate,
    )

    return audio_output, out_stream, resampler


def stream_av(config: StreamConfig, stop_event: threading.Event) -> None:
    """Stream video and audio from source to HomeKit client via SRTP.

    Single RTSP connection, demuxes both video and audio. Video is
    either passed through (copy) or transcoded. Audio is decoded,
    resampled, and re-encoded as Opus with the exact frame duration
    requested by the HomeKit client.
    """
    vc = config.video
    ac = config.audio

    _LOGGER.info(
        "Starting stream: source=%s video_codec=%s audio=%s",
        config.source,
        vc.codec,
        f"{ac.codec} {ac.sample_rate_khz}kHz {ac.packet_time_ms}ms"
        if ac
        else "disabled",
    )

    # Open the input source (RTSP camera stream)
    input_options: dict[str, str] = {}
    # Default to TCP transport for RTSP/RTSPS sources to avoid
    # UDP packet loss issues and to support TLS (rtsps://)
    if config.source.startswith(("rtsp://", "rtsps://")):
        input_options["rtsp_transport"] = "tcp"
    if config.input_options:
        input_options.update(config.input_options)

    _LOGGER.debug("Opening source %s with options %s", config.source, input_options)

    try:
        input_container = av.open(
            config.source,
            options=input_options,
            timeout=(INPUT_TIMEOUT, INPUT_TIMEOUT),
        )
    except av.FFmpegError:
        _LOGGER.exception("Failed to open source %s", config.source)
        return

    with input_container:
        # Find input streams
        if not input_container.streams.video:
            _LOGGER.error("No video stream found in source")
            return

        in_video = input_container.streams.video[0]
        in_audio = (
            input_container.streams.audio[0]
            if ac and input_container.streams.audio
            else None
        )

        _LOGGER.info(
            "Input: video=%s %dx%d, audio=%s",
            in_video.codec_context.name,
            in_video.codec_context.width,
            in_video.codec_context.height,
            (
                f"{in_audio.codec_context.name} {in_audio.codec_context.sample_rate}Hz"
                if in_audio
                else "none"
            ),
        )

        # Set up output containers
        try:
            video_output, out_video = _setup_video_output(config, in_video)
        except av.FFmpegError:
            _LOGGER.exception("Failed to open video SRTP output")
            return

        audio_output = None
        out_audio = None
        resampler = None

        if in_audio and ac:
            try:
                audio_output, out_audio, resampler = _setup_audio_output(
                    config,
                )
            except av.FFmpegError:
                _LOGGER.exception("Failed to open audio SRTP output")
                # Continue with video only
                in_audio = None

        # Build the list of streams to demux
        demux_streams: list[av.stream.Stream] = [in_video]
        if in_audio:
            demux_streams.append(in_audio)

        video_copy = vc.codec == CODEC_COPY

        _LOGGER.info("Streaming")

        try:
            _stream_loop(
                input_container,
                demux_streams,
                in_video,
                in_audio,
                video_output,
                out_video,
                audio_output,
                out_audio,
                resampler,
                video_copy,
                stop_event,
            )
        except av.FFmpegError:
            _LOGGER.exception("Streaming error")
        finally:
            video_output.close()
            if audio_output:
                audio_output.close()


def _mux_audio(
    packet: av.Packet,
    resampler: AudioResampler,
    out_audio: AudioStream,
    audio_output: av.container.OutputContainer,
    a_packets: int,
) -> int:
    """Decode, resample, encode, and mux one audio packet.

    Regenerates timestamps from zero (like go2rtc) instead of using
    the encoder's timestamps which can be negative due to Opus
    lookahead. Apple only cares about proper monotonic timestamps
    based on the requested sample rate.

    Returns updated packet count, or -1 if audio muxing failed
    and should be disabled for the rest of the stream.
    """
    for frame in packet.decode():
        for resampled in resampler.resample(frame):  # type: ignore[arg-type]
            for out_pkt in out_audio.encode(resampled):
                # Override encoder timestamps with monotonic counter;
                # Opus encoder produces negative pts for priming packets
                # and the RTP muxer rejects unsigned-incompatible values
                out_pkt.pts = a_packets * (out_pkt.duration or 0)
                out_pkt.dts = out_pkt.pts
                if a_packets == 0:
                    _LOGGER.debug(
                        "First audio packet: size=%d pts=%s dts=%s duration=%s",
                        out_pkt.size,
                        out_pkt.pts,
                        out_pkt.dts,
                        out_pkt.duration,
                    )
                try:
                    audio_output.mux(out_pkt)
                except av.FFmpegError:
                    _LOGGER.exception("Audio mux failed, disabling audio")
                    return -1
                a_packets += 1
    return a_packets


def _stream_loop(
    input_container: av.container.InputContainer,
    demux_streams: list[av.stream.Stream],
    in_video: av.stream.Stream,
    in_audio: av.stream.Stream | None,
    video_output: av.container.OutputContainer,
    out_video: av.stream.Stream,
    audio_output: av.container.OutputContainer | None,
    out_audio: AudioStream | None,
    resampler: AudioResampler | None,
    video_copy: bool,
    stop_event: threading.Event,
) -> None:
    """Run the main demux/remux loop."""
    start_time = time.monotonic()
    v_packets = 0
    a_packets = 0

    for packet in input_container.demux(*demux_streams):
        if stop_event.is_set():
            _LOGGER.debug("Stop requested")
            break

        if packet.dts is None:
            continue

        if packet.stream == in_video:
            if video_copy:
                packet.stream = out_video
                video_output.mux(packet)
                v_packets += 1
            else:
                for frame in packet.decode():
                    for out_pkt in out_video.encode(frame):  # type: ignore[attr-defined]
                        video_output.mux(out_pkt)
                        v_packets += 1

        elif (
            packet.stream == in_audio
            and audio_output is not None
            and out_audio is not None
            and resampler is not None
        ):
            a_packets = _mux_audio(
                packet, resampler, out_audio, audio_output, a_packets
            )
            if a_packets == -1:
                # Audio mux failed; disable audio for rest of stream
                in_audio = None

    # Flush encoders
    if not stop_event.is_set():
        if not video_copy:
            for out_pkt in out_video.encode(None):  # type: ignore[attr-defined]
                video_output.mux(out_pkt)
                v_packets += 1
        if out_audio is not None and audio_output is not None and a_packets != -1:
            for out_pkt in out_audio.encode(None):
                audio_output.mux(out_pkt)
                a_packets += 1

    elapsed = time.monotonic() - start_time
    _LOGGER.info(
        "Stream ended: %d video, %d audio packets in %.1fs",
        v_packets,
        a_packets,
        elapsed,
    )


def main() -> None:
    """Entry point for the A/V streamer subprocess.

    Reads JSON config from stdin (first line), then keeps stdin open.
    Stops when stdin is closed (parent died) or SIGTERM is received.
    """
    # Read config from stdin to avoid exposing SRTP keys in process list
    config_line = sys.stdin.readline()
    if not config_line:
        _LOGGER.error("No config received on stdin")
        sys.exit(1)

    config_data = json.loads(config_line)
    _LOGGER.debug("Received config: %s", config_data)
    config = StreamConfig.from_dict(config_data)

    stop_event = threading.Event()

    def handle_signal(signum: int, _frame: Any) -> None:
        _LOGGER.info("Received signal %d, stopping", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Monitor stdin for parent liveness
    def watch_stdin() -> None:
        with contextlib.suppress(OSError):
            sys.stdin.read()
        _LOGGER.info("Parent closed stdin, stopping")
        stop_event.set()

    stdin_thread = threading.Thread(target=watch_stdin, daemon=True)
    stdin_thread.start()

    stream_av(config, stop_event)


if __name__ == "__main__":
    main()
