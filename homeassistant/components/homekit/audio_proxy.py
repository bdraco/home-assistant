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
import socket
import struct
import sys

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


def _run_proxy(
    dest_addr: str,
    dest_port: int,
    srtp_key_b64: str,
    target_clock_rate: int,
) -> None:
    """Run the audio proxy loop (blocking, for subprocess use)."""
    srtp = _SRTPContext(srtp_key_b64)
    ratio = target_clock_rate / SRTP_OPUS_CLOCK_RATE

    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.bind(("127.0.0.1", 0))
    local_port = recv_sock.getsockname()[1]

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_sock.bind(("0.0.0.0", dest_port))

    # Signal the local port to the parent process
    sys.stdout.write(f"{local_port}\n")
    sys.stdout.flush()

    dest = (dest_addr, dest_port)
    try:
        while True:
            data = recv_sock.recv(2048)
            if len(data) < 12:
                continue

            # Convert timestamp from 48000 Hz to negotiated sample rate
            ts = struct.unpack_from("!I", data, 4)[0]
            new_ts = int(ts * ratio) & 0xFFFFFFFF
            packet = bytearray(data)
            struct.pack_into("!I", packet, 4, new_ts)

            srtp_packet = srtp.encrypt(bytes(packet))
            send_sock.sendto(srtp_packet, dest)
    except OSError:
        pass
    finally:
        recv_sock.close()
        send_sock.close()


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
        self.local_port: int = 0

    async def async_start(self) -> None:
        """Start the proxy subprocess."""
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "homeassistant.components.homekit.audio_proxy",
            self._dest_addr,
            str(self._dest_port),
            self._srtp_key_b64,
            str(self._target_clock_rate),
            stdout=asyncio.subprocess.PIPE,
        )
        assert self._process.stdout is not None
        line = await self._process.stdout.readline()
        self.local_port = int(line.strip())

        _LOGGER.debug(
            "Audio proxy subprocess started (PID %d) on port %d -> %s:%d (clock %d->%d)",
            self._process.pid,
            self.local_port,
            self._dest_addr,
            self._dest_port,
            SRTP_OPUS_CLOCK_RATE,
            self._target_clock_rate,
        )

    def async_stop(self) -> None:
        """Stop the proxy subprocess."""
        if self._process and self._process.returncode is None:
            self._process.kill()
            self._process = None


if __name__ == "__main__":
    _run_proxy(
        dest_addr=sys.argv[1],
        dest_port=int(sys.argv[2]),
        srtp_key_b64=sys.argv[3],
        target_clock_rate=int(sys.argv[4]),
    )
