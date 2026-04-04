"""Analyze raw HID reports captured via the UART debug-frame stream.

This tool is intentionally evidence-first: it does not assume a controller layout.
It helps you answer questions like:

- What report lengths are we receiving?
- What is the first byte (report ID) distribution?
- Which byte offsets change the most when I press inputs?
- Do the reports *look like* a known Nintendo-style 0x30 report (report_id=0x30, len≈49)?

Input formats
-------------

1) Binary UART capture (recommended)

If you captured the raw UART stream to a file (e.g., via a USB-UART dongle),
pass that file directly. This tool understands the framing documented in
`docs/serial-protocol.md`.

  python tools/analyze_hid_reports.py capture.bin

2) Text output from decode_uart_log.py

If you already ran `tools/decode_uart_log.py` and saved its stdout to a file,
use --from-text:

  python tools/analyze_hid_reports.py decoded.txt --from-text

Notes
-----

- Only frames with the 0xFF debug marker are treated as HID reports.
- Key-event frames (len==1) are ignored.

"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import re
import sys
from typing import Iterable, Iterator

SYNC0 = 0xAA
SYNC1 = 0x55


def iter_frames(data: bytes) -> Iterator[bytes]:
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


_HID_LINE_RE = re.compile(r"^hid_report\[(\d+)\]:\s*([0-9a-fA-F ]+)$")


def iter_reports_from_text(lines: Iterable[str]) -> Iterator[bytes]:
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = _HID_LINE_RE.match(line)
        if not m:
            continue
        hex_part = m.group(2).strip()
        if not hex_part:
            continue
        try:
            yield bytes.fromhex(hex_part)
        except ValueError:
            continue


def iter_reports_from_uart_bin(data: bytes) -> Iterator[bytes]:
    for payload in iter_frames(data):
        if len(payload) < 2:
            continue
        if payload[0] != 0xFF:
            continue
        n = payload[1]
        report = payload[2 : 2 + n]
        if report:
            yield report


@dataclasses.dataclass
class Stats:
    report_count: int = 0
    lengths: collections.Counter[int] = dataclasses.field(default_factory=collections.Counter)
    first_bytes: collections.Counter[int] = dataclasses.field(default_factory=collections.Counter)


def summarize_reports(reports: list[bytes]) -> Stats:
    st = Stats()
    for r in reports:
        st.report_count += 1
        st.lengths[len(r)] += 1
        st.first_bytes[r[0]] += 1
    return st


def per_offset_change_counts(reports: list[bytes], length: int) -> tuple[list[int], list[int]]:
    """Return (byte_change_counts, bit_flip_counts) for reports of a specific length."""

    selected = [r for r in reports if len(r) == length]
    if len(selected) < 2:
        return ([0] * length, [0] * length)

    byte_changes = [0] * length
    bit_flips = [0] * length

    prev = selected[0]
    for cur in selected[1:]:
        for i, (a, b) in enumerate(zip(prev, cur)):
            if a != b:
                byte_changes[i] += 1
                bit_flips[i] += (a ^ b).bit_count()
        prev = cur

    return byte_changes, bit_flips


def format_counter_hex(counter: collections.Counter[int], max_items: int = 10) -> str:
    items = counter.most_common(max_items)
    return ", ".join([f"0x{k:02X}×{v}" for k, v in items])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="Binary UART capture (.bin) or decode text output")
    ap.add_argument("--from-text", action="store_true", help="Parse text lines like 'hid_report[n]: ..'")
    ap.add_argument("--top", type=int, default=12, help="How many changing offsets to print")
    ap.add_argument(
        "--max-diffs",
        type=int,
        default=0,
        help="If >0, print up to N report-to-report diffs for the most common length",
    )

    args = ap.parse_args(argv)

    if args.from_text:
        text = open(args.path, "r", encoding="utf-8", errors="replace").read().splitlines()
        reports = list(iter_reports_from_text(text))
    else:
        data = open(args.path, "rb").read()
        reports = list(iter_reports_from_uart_bin(data))

    if not reports:
        print("No HID reports found (did you enable UART debug frames on the ESP32 host?).", file=sys.stderr)
        return 2

    st = summarize_reports(reports)
    print(f"reports: {st.report_count}")
    print(f"lengths: {dict(st.lengths.most_common())}")
    print(f"first bytes: {format_counter_hex(st.first_bytes)}")

    most_common_len, _ = st.lengths.most_common(1)[0]
    print(f"most common length: {most_common_len}")

    # Lightweight recognition hint (not a guarantee): Nintendo-style 0x30 reports.
    n_0x30 = sum(1 for r in reports if len(r) == 49 and r[0] == 0x30)
    if n_0x30:
        print(f"hint: {n_0x30}/{st.report_count} reports are len=49 and start with 0x30 (Nintendo-style input report candidate)")

    byte_changes, bit_flips = per_offset_change_counts(reports, most_common_len)
    ranked = sorted(range(most_common_len), key=lambda i: (byte_changes[i], bit_flips[i]), reverse=True)

    print("\nTop changing byte offsets (for most common length):")
    for i in ranked[: args.top]:
        print(f"  [{i:02d}] changes={byte_changes[i]:5d} bitflips={bit_flips[i]:5d}")

    if args.max_diffs > 0:
        selected = [r for r in reports if len(r) == most_common_len]
        print("\nDiff samples:")
        prev = selected[0]
        shown = 0
        for cur in selected[1:]:
            if prev != cur:
                # Print a compact diff line: show bytes that changed.
                changes = []
                for i, (a, b) in enumerate(zip(prev, cur)):
                    if a != b:
                        changes.append(f"{i}:{a:02X}->{b:02X}")
                print("  " + " ".join(changes[:80]))
                shown += 1
                if shown >= args.max_diffs:
                    break
            prev = cur

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
