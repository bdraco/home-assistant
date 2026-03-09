"""Audio RTP proxy for HomeKit camera streaming.

FFmpeg's RTP muxer uses a 48000 Hz clock rate for Opus (per RFC 7587),
but Apple's HomeKit implementation expects the RTP timestamps to use
the negotiated sample rate (e.g., 16000 Hz). This proxy receives plain
RTP from FFmpeg on a local UDP port, converts the timestamps from
48000 Hz to the negotiated rate, encrypts with SRTP, and forwards to
the HomeKit client.

Runs as a subprocess to avoid blocking the main event loop with crypto.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import socket
import struct
import sys
import traceback

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

SRTP_OPUS_CLOCK_RATE = 48000


def _derive_srtp_key(
    master_key: bytes, master_salt: bytes, label: int, length: int
) -> bytes:
    """Derive an SRTP session key per RFC 3711 Section 4.3.1."""
    key_id = label << 48
    salt_int = int.from_bytes(master_salt, "big")
    x = key_id ^ salt_int
    iv = x.to_bytes(14, "big") + b"\x00\x00"

    cipher = Cipher(algorithms.AES(master_key), modes.CTR(iv))
    encryptor = cipher.encryptor()
    return (encryptor.update(b"\x00" * length) + encryptor.finalize())[:length]


class _SRTPContext:
    """SRTP encryption context for AES_CM_128_HMAC_SHA1_80."""

    def __init__(self, master_key_b64: str) -> None:
        """Initialize from a base64-encoded master key (16 key + 14 salt)."""
        key_material = base64.b64decode(master_key_b64)
        master_key = key_material[:16]
        master_salt = key_material[16:30]

        self._session_key = _derive_srtp_key(master_key, master_salt, 0, 16)
        self._session_auth_key = _derive_srtp_key(master_key, master_salt, 1, 20)
        self._session_salt = _derive_srtp_key(master_key, master_salt, 2, 14)
        self._roc: int = 0
        self._last_seq: int = 0

    def encrypt(self, rtp_packet: bytes) -> bytes:
        """Encrypt an RTP packet to produce an SRTP packet."""
        header_len = 12
        cc = rtp_packet[0] & 0x0F
        header_len += cc * 4
        if (rtp_packet[0] >> 4) & 1:  # Extension bit
            ext_length = struct.unpack_from("!H", rtp_packet, header_len + 2)[0]
            header_len += 4 + ext_length * 4

        header = rtp_packet[:header_len]
        payload = rtp_packet[header_len:]

        ssrc = struct.unpack_from("!I", rtp_packet, 8)[0]
        seq = struct.unpack_from("!H", rtp_packet, 2)[0]

        if seq < self._last_seq and (self._last_seq - seq) > 0x8000:
            self._roc += 1
        self._last_seq = seq

        packet_index = (self._roc << 16) | seq

        iv = bytearray(16)
        struct.pack_into("!I", iv, 4, ssrc)
        iv[8:14] = packet_index.to_bytes(6, "big")
        for i in range(14):
            iv[i] ^= self._session_salt[i]

        cipher = Cipher(algorithms.AES(self._session_key), modes.CTR(bytes(iv)))
        encryptor = cipher.encryptor()
        encrypted_payload = encryptor.update(payload) + encryptor.finalize()

        srtp_packet = header + encrypted_payload
        auth_data = srtp_packet + struct.pack("!I", self._roc)
        auth_tag = hmac.new(self._session_auth_key, auth_data, hashlib.sha1).digest()[
            :10
        ]

        return srtp_packet + auth_tag


_RECV_TIMEOUT_SECONDS = 5.0


def _run_proxy(
    dest_addr: str,
    dest_port: int,
    srtp_key_b64: str,
    target_clock_rate: int,
) -> int:
    """Run the audio proxy loop (blocking, for subprocess use).

    Returns exit code: 0 for clean shutdown, 1 for error.
    """
    try:
        srtp = _SRTPContext(srtp_key_b64)
    except Exception:  # noqa: BLE001 - subprocess entry point
        traceback.print_exc(file=sys.stderr)
        return 1

    ratio = target_clock_rate / SRTP_OPUS_CLOCK_RATE
    parent_pid = os.getppid()

    try:
        recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recv_sock.settimeout(_RECV_TIMEOUT_SECONDS)
        recv_sock.bind(("127.0.0.1", 0))
        local_port = recv_sock.getsockname()[1]
    except OSError:
        traceback.print_exc(file=sys.stderr)
        return 1

    try:
        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # SO_REUSEADDR allows quick rebind if a previous proxy just released
        # the port (e.g. stream restart)
        send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind to 0.0.0.0 so the kernel picks the correct source IP
        # for the route to the HomeKit client
        send_sock.bind(("0.0.0.0", dest_port))
    except OSError:
        traceback.print_exc(file=sys.stderr)
        recv_sock.close()
        return 1

    # Signal the local port to the parent process
    sys.stdout.write(f"{local_port}\n")
    sys.stdout.flush()

    dest = (dest_addr, dest_port)
    packets_forwarded = 0
    try:
        while True:
            try:
                data = recv_sock.recv(2048)
            except TimeoutError:
                # Check if parent process is still alive to avoid orphaning
                if os.getppid() != parent_pid:
                    break
                continue
            if len(data) < 12:
                continue

            # Convert timestamp from 48000 Hz to negotiated sample rate
            ts = struct.unpack_from("!I", data, 4)[0]
            new_ts = int(ts * ratio) & 0xFFFFFFFF
            packet = bytearray(data)
            struct.pack_into("!I", packet, 4, new_ts)

            srtp_packet = srtp.encrypt(bytes(packet))
            send_sock.sendto(srtp_packet, dest)
            packets_forwarded += 1
    except OSError as err:
        sys.stderr.write(
            f"Audio proxy socket error after {packets_forwarded} packets: {err}\n"
        )
    except Exception:  # noqa: BLE001 - subprocess entry point
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        recv_sock.close()
        send_sock.close()

    return 0


class AudioProxy:
    """Proxy that converts FFmpeg's Opus RTP timestamps for HomeKit.

    Runs as a subprocess to keep crypto work off the main event loop.
    """

    def __init__(
        self,
        dest_addr: str,
        dest_port: int,
        srtp_key_b64: str,
        target_clock_rate: int,
    ) -> None:
        """Initialize the audio proxy."""
        self._dest_addr = dest_addr
        self._dest_port = dest_port
        self._srtp_key_b64 = srtp_key_b64
        self._target_clock_rate = target_clock_rate
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self.local_port: int = 0

    async def async_start(self) -> None:
        """Start the proxy subprocess."""
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "homeassistant.components.homekit.audio_proxy",
            self._dest_addr,
            str(self._dest_port),
            str(self._target_clock_rate),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Pass SRTP key via stdin to avoid exposing it in process args
        if self._process.stdin:
            self._process.stdin.write(self._srtp_key_b64.encode() + b"\n")
            await self._process.stdin.drain()
            self._process.stdin.close()

        if self._process.stdout is None:
            _LOGGER.error("Audio proxy subprocess has no stdout")
            return

        line = await self._process.stdout.readline()
        if not line:
            # Process exited before writing the port — read stderr for details
            stderr_output = b""
            if self._process.stderr:
                stderr_output = await self._process.stderr.read()
            _LOGGER.error(
                "Audio proxy subprocess failed to start: %s",
                stderr_output.decode(errors="replace").strip(),
            )
            return

        self.local_port = int(line.strip())

        # Log stderr in the background so errors are visible in HA logs
        if self._process.stderr:
            self._stderr_task = asyncio.create_task(
                self._log_stderr(self._process.stderr)
            )

        _LOGGER.debug(
            "Audio proxy subprocess started (PID %d) on port %d -> %s:%d"
            " (clock %d->%d)",
            self._process.pid,
            self.local_port,
            self._dest_addr,
            self._dest_port,
            SRTP_OPUS_CLOCK_RATE,
            self._target_clock_rate,
        )

    @staticmethod
    async def _log_stderr(stderr: asyncio.StreamReader) -> None:
        """Forward subprocess stderr to HA logger."""
        while True:
            line = await stderr.readline()
            if not line:
                return
            _LOGGER.warning("Audio proxy: %s", line.decode(errors="replace").rstrip())

    async def async_stop(self) -> None:
        """Stop the proxy subprocess and wait for port release."""
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            self._stderr_task = None
        if self._process and self._process.returncode is None:
            self._process.kill()
            await self._process.wait()
            self._process = None


if __name__ == "__main__":
    # SRTP key is passed via stdin to avoid exposing it in process args
    _srtp_key = sys.stdin.readline().strip()
    sys.exit(
        _run_proxy(
            dest_addr=sys.argv[1],
            dest_port=int(sys.argv[2]),
            srtp_key_b64=_srtp_key,
            target_clock_rate=int(sys.argv[3]),
        )
    )
