from __future__ import annotations

import json
import logging
import queue
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import serial

log = logging.getLogger("joycon_helper.serial")

# ---------------------------------------------------------------------------
# Binary config-block protocol constants  (must match config_block.h)
# ---------------------------------------------------------------------------
CONFIG_BLOCK_MARKER = 0xCB

CFG_BLOCK_MAPPING    = 0x01
CFG_BLOCK_MACRO      = 0x02
CFG_BLOCK_LAYER      = 0x03
CFG_BLOCK_CHORD      = 0x04
CFG_BLOCK_STICK      = 0x05
CFG_BLOCK_ZONE       = 0x06
CFG_BLOCK_ACTIVATOR  = 0x07
CFG_BLOCK_GYRO       = 0x08
CFG_BLOCK_PROFILE_BEGIN = 0xF0
CFG_BLOCK_PROFILE_END   = 0xF1
CFG_BLOCK_PROFILE_ABORT = 0xF2
CFG_BLOCK_BULK_JSON  = 0xFE


def _crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE (same polynomial as xmodem variant used in firmware)."""
    crc = init
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


@dataclass
class SerialLine:
    raw: str
    parsed: Optional[dict[str, Any]]


class SerialClient:
    def __init__(self) -> None:
        self._ser: Optional[serial.Serial] = None
        self._rx_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connection_lost = threading.Event()
        # Bounded queue: drop oldest events if the consumer can't keep up.
        self.rx: "queue.Queue[SerialLine]" = queue.Queue(maxsize=512)

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    @property
    def connection_lost(self) -> bool:
        """True when the RX thread exited due to a read error (cable unplug, etc.)."""
        return self._connection_lost.is_set()

    def connect(self, port: str, baud: int = 115200) -> None:
        self.disconnect()
        self._stop.clear()
        self._connection_lost.clear()
        log.info("Opening serial port %s @ %d", port, baud)
        self._ser = serial.Serial(port=port, baudrate=baud, timeout=0.1)
        self._rx_thread = threading.Thread(target=self._rx_loop, name="serial-rx", daemon=True)
        self._rx_thread.start()
        log.info("Serial RX thread started")

    def disconnect(self) -> None:
        self._stop.set()
        if self._ser is not None:
            log.info("Closing serial port")
            try:
                self._ser.close()
            except Exception:
                log.debug("Error closing serial port", exc_info=True)
        self._ser = None
        if self._rx_thread is not None:
            self._rx_thread.join(timeout=2.0)
            self._rx_thread = None

    def send_obj(self, obj: dict[str, Any]) -> None:
        if not self.is_connected:
            raise RuntimeError("Not connected")
        line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
        if self._ser is None:
            raise RuntimeError("Serial port not open")
        self._ser.write(line.encode("utf-8"))

    def send_text_line(self, text: str) -> None:
        if not self.is_connected:
            raise RuntimeError("Not connected")
        if not text.endswith("\n"):
            text += "\n"
        if self._ser is None:
            raise RuntimeError("Serial port not open")
        self._ser.write(text.encode("utf-8"))

    # ------------------------------------------------------------------
    # Binary config-block transport
    # ------------------------------------------------------------------

    def send_raw(self, data: bytes) -> None:
        """Send raw bytes over the serial port (no framing added)."""
        if not self.is_connected or self._ser is None:
            raise RuntimeError("Not connected")
        self._ser.write(data)

    def send_config_block(self, block_type: int, slot: int, payload: bytes) -> None:
        """Build and send a single binary config block.

        Frame: 0xCB <type:u8> <slot:u8> <len:u16-LE> <payload> <crc16:u16-LE>
        CRC covers type + slot + len + payload.
        """
        if not self.is_connected or self._ser is None:
            raise RuntimeError("Not connected")
        if len(payload) > 4096:
            raise ValueError(f"Payload too large ({len(payload)} bytes, max 4096)")

        header = struct.pack("<BBH", block_type, slot, len(payload))
        crc_data = header + payload
        crc = _crc16_ccitt(crc_data)

        frame = bytes([CONFIG_BLOCK_MARKER]) + crc_data + struct.pack("<H", crc)
        self._ser.write(frame)
        log.debug(
            "Sent config block type=0x%02X slot=%d payload=%d crc=0x%04X",
            block_type, slot, len(payload), crc,
        )

    def send_profile_binary(self, slot: int, profile: dict[str, Any]) -> None:
        """Push a full profile to a device slot using the binary protocol.

        Sends PROFILE_BEGIN, then individual blocks for each section
        (mappings, macros, layers, chords, stick, zones, activators, gyro),
        then PROFILE_END to commit atomically.
        """
        name = profile.get("name", "")[:31]
        name_bytes = name.encode("utf-8")[:31]
        self.send_config_block(CFG_BLOCK_PROFILE_BEGIN, slot, name_bytes)

        try:
            # --- mappings ---
            for m in profile.get("mappings", []):
                self._send_mapping_block(slot, m)

            # --- macros ---
            for mac in profile.get("macros", []):
                self._send_macro_block(slot, mac)

            # --- layers ---
            for layer in profile.get("layers", []):
                self._send_layer_block(slot, layer)

            # --- chords ---
            for chord in profile.get("chords", []):
                self._send_chord_block(slot, chord)

            # --- stick ---
            stick = profile.get("stick")
            if stick:
                self._send_stick_block(slot, stick)

            # --- zones ---
            for zone in profile.get("zones", []):
                self._send_zone_block(slot, zone)

            # --- activators ---
            for act in profile.get("activators", []):
                self._send_activator_block(slot, act)

            # --- gyro ---
            gyro = profile.get("gyro")
            if gyro:
                self._send_gyro_block(slot, gyro)

            self.send_config_block(CFG_BLOCK_PROFILE_END, slot, b"")
        except Exception:
            log.error("Profile binary push failed — sending ABORT", exc_info=True)
            self.send_config_block(CFG_BLOCK_PROFILE_ABORT, slot, b"")
            raise

    # ------------------------------------------------------------------
    # Per-block binary encoders (private)
    # ------------------------------------------------------------------

    @staticmethod
    def _mode_to_u8(mode_str: str) -> int:
        """Convert a mapping mode string to its numeric ID."""
        _MAP = {
            "passthrough": 0, "disabled": 1, "remap": 2, "macro": 3,
            "remap_hid": 4, "double_tap": 5, "turbo": 6, "sticky_mod": 7,
            "tap_hold": 8, "oneshot_mod": 9, "auto_shift": 10,
            "mouse_button": 11, "sequential": 12, "leader": 13,
            "profile_switch": 14,
        }
        return _MAP.get(mode_str, 0)

    def _send_mapping_block(self, slot: int, m: dict) -> None:
        """Encode and send a single mapping entry.

        Binary format (matches config_block.c apply_mapping_entry):
          key_id:u8  mode:u8  target:u8  layer:u8  flags:u8
          turbo_ms:u16-LE  tap_ms:u16-LE  hold_ms:u16-LE
          seq_len:u8  seq[8]:u8
          macro_id_len:u8  macro_id[31]:u8
        Total = 5 + 6 + 1 + 8 + 1 + 31 = 52 bytes
        """
        key_id = m.get("key_id", 0)
        mode = self._mode_to_u8(m.get("mode", "passthrough"))
        target = m.get("target", 0)
        layer = m.get("layer", 0)
        flags = m.get("flags", 0)
        turbo_ms = m.get("turbo_ms", 0)
        tap_ms = m.get("tap_ms", 0)
        hold_ms = m.get("hold_ms", 0)
        seq = m.get("seq", [])[:8]
        macro_id = m.get("macro_id", "")[:31]

        buf = struct.pack("<BBBBB HHH B",
                          key_id, mode, target, layer, flags,
                          turbo_ms, tap_ms, hold_ms,
                          len(seq))
        seq_bytes = bytes(seq) + b"\x00" * (8 - len(seq))
        macro_bytes = macro_id.encode("utf-8")[:31]
        buf += seq_bytes + struct.pack("B", len(macro_bytes)) + macro_bytes + b"\x00" * (31 - len(macro_bytes))

        self.send_config_block(CFG_BLOCK_MAPPING, slot, buf)

    def _send_macro_block(self, slot: int, mac: dict) -> None:
        """Encode and send a macro definition.

        Binary format:
          id_len:u8  id[31]:u8  step_count:u8
          then per step: action:u8 keycode:u8 delay_ms:u16-LE (4 bytes each)
        """
        mid = mac.get("id", "")[:31]
        steps = mac.get("steps", [])[:128]

        mid_bytes = mid.encode("utf-8")[:31]
        buf = struct.pack("B", len(mid_bytes))
        buf += mid_bytes + b"\x00" * (31 - len(mid_bytes))
        buf += struct.pack("B", len(steps))
        for s in steps:
            action = 1 if s.get("action", "press") == "press" else 0
            buf += struct.pack("<BBH", action, s.get("keycode", 0), s.get("delay_ms", 0))

        self.send_config_block(CFG_BLOCK_MACRO, slot, buf)

    def _send_layer_block(self, slot: int, layer: dict) -> None:
        """Encode and send a layer definition.

        Binary format:
          name_len:u8  name[31]:u8  entry_count:u8
          per entry: key_id:u8 target:u8 (2 bytes each)
        """
        name = layer.get("name", "")[:31]
        entries = layer.get("entries", [])[:35]

        name_bytes = name.encode("utf-8")[:31]
        buf = struct.pack("B", len(name_bytes))
        buf += name_bytes + b"\x00" * (31 - len(name_bytes))
        buf += struct.pack("B", len(entries))
        for e in entries:
            buf += struct.pack("BB", e.get("key_id", 0), e.get("target", 0))

        self.send_config_block(CFG_BLOCK_LAYER, slot, buf)

    def _send_chord_block(self, slot: int, chord: dict) -> None:
        """Encode and send a chord definition.

        Binary format:
          key_count:u8  keys[4]:u8  target:u8
        """
        keys = chord.get("keys", [])[:4]
        target = chord.get("target", 0)

        buf = struct.pack("B", len(keys))
        buf += bytes(keys) + b"\x00" * (4 - len(keys))
        buf += struct.pack("B", target)

        self.send_config_block(CFG_BLOCK_CHORD, slot, buf)

    def _send_stick_block(self, slot: int, stick: dict) -> None:
        """Encode and send stick configuration.

        Binary format:
          deadzone:u16-LE  curve:u8  sensitivity:u16-LE  sprint_threshold:u16-LE
          sprint_multiplier:u16-LE (×100)
        """
        buf = struct.pack("<HBHHH",
                          stick.get("deadzone", 400),
                          stick.get("curve", 0),
                          stick.get("sensitivity", 100),
                          stick.get("sprint_threshold", 0),
                          int(stick.get("sprint_multiplier", 1.0) * 100))

        self.send_config_block(CFG_BLOCK_STICK, slot, buf)

    def _send_zone_block(self, slot: int, zone: dict) -> None:
        """Encode and send a zone definition.

        Binary format:
          id_len:u8  id[31]:u8  shape:u8
          cx:i16-LE  cy:i16-LE
          param1:u16-LE  param2:u16-LE  param3:u16-LE  param4:u16-LE
          angle_start:i16-LE  angle_end:i16-LE
          output_key:u8
        """
        zid = zone.get("id", "")[:31]
        shape_map = {"circle": 0, "ring": 1, "wedge": 2, "rect": 3}
        shape = shape_map.get(zone.get("shape", "circle"), 0)

        zid_bytes = zid.encode("utf-8")[:31]
        buf = struct.pack("B", len(zid_bytes))
        buf += zid_bytes + b"\x00" * (31 - len(zid_bytes))
        buf += struct.pack("<B hh HHHH hh B",
                           shape,
                           zone.get("cx", 0), zone.get("cy", 0),
                           zone.get("param1", 0), zone.get("param2", 0),
                           zone.get("param3", 0), zone.get("param4", 0),
                           zone.get("angle_start", 0), zone.get("angle_end", 0),
                           zone.get("output_key", 0))

        self.send_config_block(CFG_BLOCK_ZONE, slot, buf)

    def _send_activator_block(self, slot: int, act: dict) -> None:
        """Encode and send an activator definition.

        Binary format:
          id_len:u8  id[31]:u8  trigger:u8
          source_key:u8  output_key:u8
          threshold_ms:u16-LE  flags:u8
        """
        aid = act.get("id", "")[:31]
        trigger_map = {
            "press": 0, "release": 1, "double_press": 2,
            "long_press": 3, "chord": 4,
        }
        trigger = trigger_map.get(act.get("trigger", "press"), 0)

        aid_bytes = aid.encode("utf-8")[:31]
        buf = struct.pack("B", len(aid_bytes))
        buf += aid_bytes + b"\x00" * (31 - len(aid_bytes))
        buf += struct.pack("<B BB H B",
                           trigger,
                           act.get("source_key", 0),
                           act.get("output_key", 0),
                           act.get("threshold_ms", 0),
                           act.get("flags", 0))

        self.send_config_block(CFG_BLOCK_ACTIVATOR, slot, buf)

    def _send_gyro_block(self, slot: int, gyro: dict) -> None:
        """Encode and send gyro configuration.

        Binary format:
          enabled:u8  sensitivity_x:u16-LE  sensitivity_y:u16-LE
          deadzone:u16-LE  accel_type:u8  accel_param:u16-LE
          invert_x:u8  invert_y:u8
        """
        buf = struct.pack("<B HH H B H BB",
                          1 if gyro.get("enabled", False) else 0,
                          gyro.get("sensitivity_x", 100),
                          gyro.get("sensitivity_y", 100),
                          gyro.get("deadzone", 0),
                          gyro.get("accel_type", 0),
                          gyro.get("accel_param", 0),
                          1 if gyro.get("invert_x", False) else 0,
                          1 if gyro.get("invert_y", False) else 0)

        self.send_config_block(CFG_BLOCK_GYRO, slot, buf)

    def _rx_loop(self) -> None:
        if self._ser is None:
            return
        buffer = bytearray()
        _MAX_BUFFER = 65536  # 64 KB cap to prevent unbounded growth

        while not self._stop.is_set():
            try:
                chunk = self._ser.read(256)
            except Exception as exc:
                if not self._stop.is_set():
                    log.error("Serial read error: %s", exc, exc_info=True)
                    self._connection_lost.set()
                break

            if chunk:
                buffer.extend(chunk)

                # Cap buffer size — evict oldest data, keep partial frame
                if len(buffer) > _MAX_BUFFER:
                    last_nl = buffer.rfind(b"\n")
                    if last_nl >= 0:
                        # Keep only the incomplete tail after the last newline
                        discard = last_nl + 1
                        log.warning(
                            "Serial RX buffer exceeded %d bytes — "
                            "evicting %d bytes of oldest data",
                            _MAX_BUFFER, discard,
                        )
                        del buffer[:discard]
                    else:
                        # No newline at all — single enormous line; drop it
                        log.warning(
                            "Serial RX buffer exceeded %d bytes with no "
                            "newline — dropping %d bytes",
                            _MAX_BUFFER, len(buffer),
                        )
                        buffer.clear()
                    continue

                while True:
                    nl = buffer.find(b"\n")
                    if nl < 0:
                        break
                    raw_line = buffer[:nl + 1]
                    del buffer[:nl + 1]

                    raw = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    parsed = None
                    if raw.startswith("{") and raw.endswith("}"):
                        try:
                            parsed = json.loads(raw)
                        except Exception:
                            log.debug("JSON parse failed for line: %s", raw[:200])
                            parsed = None
                    try:
                        self.rx.put_nowait(SerialLine(raw=raw, parsed=parsed))
                    except queue.Full:
                        # Drop oldest event to make room
                        try:
                            self.rx.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            self.rx.put_nowait(SerialLine(raw=raw, parsed=parsed))
                        except queue.Full:
                            pass
            else:
                time.sleep(0.01)

        log.info("Serial RX thread exiting")
