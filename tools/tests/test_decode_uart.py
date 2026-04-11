"""Tests for the UART frame decoder (tools/decode_uart_log.py)."""

from __future__ import annotations

import sys
from pathlib import Path

# Make sure the tools directory is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decode_uart_log import SYNC0, SYNC1, iter_frames


def _build_frame(payload: bytes) -> bytes:
    """Build a valid UART frame: SYNC0 SYNC1 LEN PAYLOAD CHECKSUM."""
    length = len(payload)
    checksum = length
    for b in payload:
        checksum ^= b
    return bytes([SYNC0, SYNC1, length]) + payload + bytes([checksum & 0xFF])


class TestIterFrames:
    def test_single_key_event(self):
        """Single-byte payload with bit-7 = pressed, bits 6:0 = key_id."""
        event = 0x80 | 42  # key_id=42, pressed
        data = _build_frame(bytes([event]))
        frames = list(iter_frames(data))
        assert len(frames) == 1
        assert frames[0] == bytes([event])

    def test_multiple_frames(self):
        f1 = _build_frame(b"\x01")
        f2 = _build_frame(b"\x02")
        frames = list(iter_frames(f1 + f2))
        assert len(frames) == 2
        assert frames[0] == b"\x01"
        assert frames[1] == b"\x02"

    def test_garbage_before_frame(self):
        garbage = b"\x00\x11\x22\x33"
        valid = _build_frame(b"\x05")
        frames = list(iter_frames(garbage + valid))
        assert len(frames) == 1
        assert frames[0] == b"\x05"

    def test_bad_checksum_skipped(self):
        good = _build_frame(b"\x0A")
        bad = bytes([SYNC0, SYNC1, 1, 0x0B, 0xFF])  # wrong checksum
        frames = list(iter_frames(bad + good))
        assert len(frames) == 1
        assert frames[0] == b"\x0A"

    def test_empty_input(self):
        assert list(iter_frames(b"")) == []

    def test_truncated_input(self):
        # Only sync bytes + length, no payload
        data = bytes([SYNC0, SYNC1, 5])
        assert list(iter_frames(data)) == []

    def test_debug_hid_report_frame(self):
        """Debug frame: 0xFF, N, then N bytes of HID report data."""
        hid_report = bytes([0x30] + [0] * 48)  # 49 bytes (typical 0x30 report)
        payload = bytes([0xFF, len(hid_report)]) + hid_report
        data = _build_frame(payload)
        frames = list(iter_frames(data))
        assert len(frames) == 1
        assert frames[0][0] == 0xFF
        assert frames[0][1] == len(hid_report)

    def test_sync_constants(self):
        assert SYNC0 == 0xAA
        assert SYNC1 == 0x55

    def test_key_event_encoding(self):
        """Verify key-event byte layout: bit 7 = press/release, bits 6:0 = key_id."""
        for key_id in (0, 1, 42, 127):
            pressed_byte = 0x80 | key_id
            released_byte = key_id
            # Pressed
            assert pressed_byte & 0x80 != 0
            assert pressed_byte & 0x7F == key_id
            # Released
            assert released_byte & 0x80 == 0
            assert released_byte & 0x7F == key_id
