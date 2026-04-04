"""Decode UART frames captured from ESP32->RP2040.

This is for offline debugging only (e.g., you capture UART with a USB-UART dongle).
It is not required for gameplay.

Usage:
  python decode_uart_log.py path/to/log.bin

The log file should contain raw bytes.
"""

from __future__ import annotations

import sys

SYNC0 = 0xAA
SYNC1 = 0x55


def iter_frames(data: bytes):
    i = 0
    while i + 5 <= len(data):
        if data[i] != SYNC0 or data[i + 1] != SYNC1:
            i += 1
            continue
        length = data[i + 2]
        if i + 3 + length >= len(data):
            break
        payload = data[i + 3 : i + 3 + length]
        checksum = data[i + 3 + length]
        calc = length
        for b in payload:
            calc ^= b
        if calc == checksum:
            yield payload
            i += 4 + length
        else:
            i += 1


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python decode_uart_log.py log.bin", file=sys.stderr)
        return 2

    path = sys.argv[1]
    data = open(path, "rb").read()

    for payload in iter_frames(data):
        (event,) = payload
        pressed = bool(event & 0x80)
        key_id = event & 0x7F
        print(f"key_id={key_id:3d} {'DOWN' if pressed else 'UP'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
