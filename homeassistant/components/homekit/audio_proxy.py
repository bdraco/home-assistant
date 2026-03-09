"""Audio RTP proxy for HomeKit camera streaming.

FFmpeg's RTP muxer uses a 48000 Hz clock rate for Opus (per RFC 7587),
but Apple's HomeKit implementation expects the RTP timestamps to use
the negotiated sample rate (e.g., 16000 Hz). This proxy receives plain
RTP from FFmpeg on a local UDP port, converts the timestamps from
48000 Hz to the negotiated rate, encrypts with SRTP, and forwards to
the HomeKit client.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

SRTP_OPUS_CLOCK_RATE = 48000


def _derive_srtp_key(
    master_key: bytes, master_salt: bytes, label: int, length: int
) -> bytes:
    """Derive an SRTP session key per RFC 3711 Section 4.3.1."""
    # key_id = label << 48 (label is 8-bit, r=0 for kdr=0)
    # x = key_id XOR master_salt (both as 112-bit integers)
    # IV = x padded to 128 bits (append 2 zero bytes)
    key_id = label << 48
    salt_int = int.from_bytes(master_salt, "big")
    x = key_id ^ salt_int
    iv = x.to_bytes(14, "big") + b"\x00\x00"

    # Generate keystream using AES-128-CTR
    cipher = Cipher(algorithms.AES(master_key), modes.CTR(iv))
    encryptor = cipher.encryptor()
    return (encryptor.update(b"\x00" * length) + encryptor.finalize())[:length]


class SRTPContext:
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
        # Parse RTP header to find payload offset
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

        # Track ROC (rollover counter)
        if seq < self._last_seq and (self._last_seq - seq) > 0x8000:
            self._roc += 1
        self._last_seq = seq

        packet_index = (self._roc << 16) | seq

        # Build IV for AES-128-CTR encryption
        iv = bytearray(16)
        struct.pack_into("!I", iv, 4, ssrc)
        pi_bytes = packet_index.to_bytes(6, "big")
        iv[8:14] = pi_bytes
        for i in range(14):
            iv[i] ^= self._session_salt[i]

        # Encrypt payload
        cipher = Cipher(algorithms.AES(self._session_key), modes.CTR(bytes(iv)))
        encryptor = cipher.encryptor()
        encrypted_payload = encryptor.update(payload) + encryptor.finalize()

        # Build SRTP packet and compute auth tag
        srtp_packet = header + encrypted_payload
        auth_data = srtp_packet + struct.pack("!I", self._roc)
        auth_tag = hmac.new(self._session_auth_key, auth_data, hashlib.sha1).digest()[
            :10
        ]

        return srtp_packet + auth_tag


class _AudioProxyProtocol(asyncio.DatagramProtocol):
    """UDP protocol that receives RTP, fixes timestamps, and forwards as SRTP."""

    def __init__(
        self,
        srtp: SRTPContext,
        dest_addr: str,
        dest_port: int,
        target_clock_rate: int,
    ) -> None:
        """Initialize the proxy protocol."""
        self._srtp = srtp
        self._dest = (dest_addr, dest_port)
        self._ratio = target_clock_rate / SRTP_OPUS_CLOCK_RATE
        self._out_transport: asyncio.DatagramTransport | None = None

    def set_out_transport(self, transport: asyncio.DatagramTransport) -> None:
        """Set the outgoing transport for sending SRTP packets."""
        self._out_transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Process an incoming RTP packet from FFmpeg."""
        if len(data) < 12 or self._out_transport is None:
            return

        # Convert timestamp from 48000 Hz to negotiated sample rate
        ts = struct.unpack_from("!I", data, 4)[0]
        new_ts = int(ts * self._ratio) & 0xFFFFFFFF
        packet = bytearray(data)
        struct.pack_into("!I", packet, 4, new_ts)

        # Encrypt and forward
        srtp_packet = self._srtp.encrypt(bytes(packet))
        self._out_transport.sendto(srtp_packet, self._dest)


class AudioProxy:
    """Proxy that converts FFmpeg's Opus RTP timestamps for HomeKit.

    FFmpeg uses 48000 Hz RTP clock rate for Opus (per RFC 7587), but
    HomeKit expects the negotiated sample rate (typically 16000 Hz).
    This proxy intercepts FFmpeg's RTP output, converts timestamps,
    encrypts with SRTP, and forwards to the HomeKit client.
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
        self._in_transport: asyncio.DatagramTransport | None = None
        self._out_transport: asyncio.DatagramTransport | None = None
        self.local_port: int = 0

    async def async_start(self) -> None:
        """Start the proxy and bind to a local UDP port."""
        loop = asyncio.get_running_loop()
        srtp = SRTPContext(self._srtp_key_b64)

        protocol = _AudioProxyProtocol(
            srtp, self._dest_addr, self._dest_port, self._target_clock_rate
        )

        self._in_transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol, local_addr=("127.0.0.1", 0)
        )
        sockname = self._in_transport.get_extra_info("sockname")
        self.local_port = sockname[1]

        # Create unconnected outgoing socket for sending
        self._out_transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, local_addr=("0.0.0.0", 0)
        )
        protocol.set_out_transport(self._out_transport)

        _LOGGER.debug(
            "Audio proxy started on port %d -> %s:%d (clock %d->%d)",
            self.local_port,
            self._dest_addr,
            self._dest_port,
            SRTP_OPUS_CLOCK_RATE,
            self._target_clock_rate,
        )

    def async_stop(self) -> None:
        """Stop the proxy."""
        if self._in_transport:
            self._in_transport.close()
            self._in_transport = None
        if self._out_transport:
            self._out_transport.close()
            self._out_transport = None
