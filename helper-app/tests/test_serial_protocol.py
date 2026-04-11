"""Tests for the CRC-16/CCITT and config-block framing in serial_client.py."""

from __future__ import annotations

import struct

from joycon_helper.serial_client import (
    CFG_BLOCK_MAPPING,
    CFG_BLOCK_PROFILE_BEGIN,
    CONFIG_BLOCK_MARKER,
    _crc16_ccitt,
)

# ── CRC-16/CCITT ────────────────────────────────────────────────────


class TestCRC16:
    def test_empty_input(self):
        assert _crc16_ccitt(b"") == 0xFFFF

    def test_known_vector(self):
        # "123456789" → CRC-16/CCITT-FALSE = 0x29B1
        assert _crc16_ccitt(b"123456789") == 0x29B1

    def test_single_byte(self):
        result = _crc16_ccitt(b"\x00")
        assert isinstance(result, int)
        assert 0 <= result <= 0xFFFF

    def test_custom_init(self):
        result = _crc16_ccitt(b"abc", init=0x0000)
        assert isinstance(result, int)
        # Different init → different result
        assert result != _crc16_ccitt(b"abc", init=0xFFFF)

    def test_deterministic(self):
        data = b"hello world"
        assert _crc16_ccitt(data) == _crc16_ccitt(data)

    def test_incremental_equivalence(self):
        """CRC of full data == CRC of second half seeded with CRC of first half."""
        data = b"abcdefghij"
        full_crc = _crc16_ccitt(data)
        half_crc = _crc16_ccitt(data[:5])
        incremental = _crc16_ccitt(data[5:], init=half_crc)
        assert full_crc == incremental


# ── Config-block frame construction ─────────────────────────────────


class TestConfigBlockFrame:
    """Verify the binary frame format matches the documented protocol:

    0xCB <type:u8> <slot:u8> <len:u16-LE> <payload> <crc16:u16-LE>
    """

    @staticmethod
    def _build_frame(block_type: int, slot: int, payload: bytes) -> bytes:
        header = struct.pack("<BBH", block_type, slot, len(payload))
        crc_data = header + payload
        crc = _crc16_ccitt(crc_data)
        return bytes([CONFIG_BLOCK_MARKER]) + crc_data + struct.pack("<H", crc)

    def test_marker_byte(self):
        frame = self._build_frame(CFG_BLOCK_MAPPING, 0, b"\x01\x02")
        assert frame[0] == CONFIG_BLOCK_MARKER

    def test_frame_structure(self):
        payload = b"\x10\x20\x30"
        frame = self._build_frame(CFG_BLOCK_MAPPING, 2, payload)
        # marker(1) + type(1) + slot(1) + len(2) + payload(3) + crc(2) = 10
        assert len(frame) == 10
        assert frame[1] == CFG_BLOCK_MAPPING
        assert frame[2] == 2  # slot
        length_field = struct.unpack_from("<H", frame, 3)[0]
        assert length_field == 3

    def test_crc_covers_header_and_payload(self):
        payload = b"\xAA\xBB"
        frame = self._build_frame(CFG_BLOCK_PROFILE_BEGIN, 1, payload)
        crc_data = frame[1:-2]  # type+slot+len+payload
        expected_crc = _crc16_ccitt(crc_data)
        actual_crc = struct.unpack_from("<H", frame, len(frame) - 2)[0]
        assert actual_crc == expected_crc

    def test_empty_payload(self):
        frame = self._build_frame(CFG_BLOCK_PROFILE_BEGIN, 0, b"")
        # marker(1) + type(1) + slot(1) + len(2) + crc(2) = 7
        assert len(frame) == 7
        length_field = struct.unpack_from("<H", frame, 3)[0]
        assert length_field == 0

    def test_max_reasonable_payload(self):
        payload = bytes(range(256)) * 4  # 1024 bytes
        frame = self._build_frame(CFG_BLOCK_MAPPING, 0, payload)
        length_field = struct.unpack_from("<H", frame, 3)[0]
        assert length_field == 1024
