from __future__ import annotations

import contextlib
import json
import logging
import queue
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, ClassVar

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
CFG_BLOCK_FLICK_STICK = 0x09
CFG_BLOCK_STICK_ACCEL = 0x0A
CFG_BLOCK_PROFILE_BEGIN = 0x10
CFG_BLOCK_PROFILE_END   = 0x11
CFG_BLOCK_PROFILE_ABORT = 0x12
CFG_BLOCK_BULK_JSON  = 0xFE


def _crc16_ccitt(data: bytes, init: int = 0x0000) -> int:
    """CRC-16/CCITT (xmodem init=0x0000), matching firmware config_block_crc16()."""
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
    parsed: dict[str, Any] | None


@dataclass
class SerialHistoryEntry:
    timestamp: float
    direction: str
    raw: str
    parsed: dict[str, Any] | None


class SerialClient:
    def __init__(self) -> None:
        self._ser: serial.Serial | None = None
        self._rx_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connection_lost = threading.Event()
        # Bounded queue: drop oldest events if the consumer can't keep up.
        self.rx: queue.Queue[SerialLine] = queue.Queue(maxsize=512)
        self._history: deque[SerialHistoryEntry] = deque(maxlen=256)

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
        self._history.clear()
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
        try:
            self._ser.write(line.encode("utf-8"))
            self._record_history("tx", line.rstrip("\n"), obj)
            log.debug("Serial TX JSON: %s", self._trim_for_log(line.rstrip("\n")))
        except Exception as exc:
            log.error("Serial write failed: %s", exc, exc_info=True)
            self._connection_lost.set()
            raise

    def send_text_line(self, text: str) -> None:
        if not self.is_connected:
            raise RuntimeError("Not connected")
        if not text.endswith("\n"):
            text += "\n"
        if self._ser is None:
            raise RuntimeError("Serial port not open")
        try:
            self._ser.write(text.encode("utf-8"))
            self._record_history("tx", text.rstrip("\n"), None)
            log.debug("Serial TX text: %s", self._trim_for_log(text.rstrip("\n")))
        except Exception as exc:
            log.error("Serial write failed: %s", exc, exc_info=True)
            self._connection_lost.set()
            raise

    def drain_rx_queue(self, *, limit: int | None = None) -> list[SerialLine]:
        """Drain pending RX lines from the queue and return them oldest-first."""
        drained: list[SerialLine] = []
        max_items = limit if limit is not None else self.rx.maxsize
        while len(drained) < max_items:
            with contextlib.suppress(queue.Empty):
                drained.append(self.rx.get_nowait())
                continue
            break
        return drained

    def snapshot_history(self, *, limit: int = 50) -> list[SerialHistoryEntry]:
        """Return the most recent TX/RX history entries oldest-first."""
        if limit <= 0:
            return []
        history = list(self._history)
        return history[-limit:]

    @staticmethod
    def _trim_for_log(text: str, *, limit: int = 240) -> str:
        if len(text) <= limit:
            return text
        return f"{text[:limit]}...<+{len(text) - limit} chars>"

    def _record_history(self, direction: str, raw: str, parsed: dict[str, Any] | None) -> None:
        self._history.append(
            SerialHistoryEntry(
                timestamp=time.time(),
                direction=direction,
                raw=raw,
                parsed=parsed,
            )
        )

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
        if len(payload) > 8192:
            raise ValueError(f"Payload too large ({len(payload)} bytes, max 8192)")

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

        Uses CFG_BLOCK_BULK_JSON to avoid per-block format mismatches and
        to support key_id values beyond 255.
        """
        self._validate_profile(profile)

        json_str = json.dumps(profile, separators=(",", ":"), ensure_ascii=False)
        payload = json_str.encode("utf-8")
        self.send_config_block(CFG_BLOCK_BULK_JSON, slot, payload)

    # ------------------------------------------------------------------
    # Profile validation
    # ------------------------------------------------------------------

    _VALID_MODES = frozenset({
        "passthrough", "disabled", "disable", "remap", "macro", "remap_hid",
        "double_tap", "turbo", "sticky_mod", "sticky", "tap_hold",
        "oneshot_mod", "oneshot", "auto_shift", "mouse_button", "gamepad_button",
        "sequential", "leader", "profile_switch",
    })

    @staticmethod
    def _validate_profile(profile: dict[str, Any]) -> None:
        """Validate profile dict structure before binary encoding.

        Raises ValueError with a descriptive message on the first problem found.
        """
        if not isinstance(profile, dict):
            raise ValueError("Profile must be a dict")

        # name
        name = profile.get("name", "")
        if not isinstance(name, str):
            raise ValueError("Profile 'name' must be a string")

        # mappings (firmware schema): object keyed by input key_id string
        mappings = profile.get("mappings", {})
        if mappings is None:
            mappings = {}
        if not isinstance(mappings, dict):
            raise ValueError("Profile 'mappings' must be an object")
        for kid_s, m in mappings.items():
            try:
                kid = int(kid_s)
            except Exception:
                continue
            if kid < 0 or kid > 639:
                raise ValueError(f"mapping key_id out of range: {kid}")
            if not isinstance(m, dict):
                raise ValueError(f"mappings['{kid_s}'] must be a dict")
            mode = m.get("type", "passthrough")
            if mode not in SerialClient._VALID_MODES:
                log.warning("mappings['%s'] has unrecognised type '%s' — defaulting to passthrough", kid_s, mode)

        # macros
        macros = profile.get("macros", [])
        if not isinstance(macros, list):
            raise ValueError("Profile 'macros' must be a list")
        for i, mac in enumerate(macros):
            if not isinstance(mac, dict):
                raise ValueError(f"macros[{i}] must be a dict")
            if not mac.get("id"):
                raise ValueError(f"macros[{i}] missing 'id'")
            steps = mac.get("steps", [])
            if not isinstance(steps, list):
                raise ValueError(f"macros[{i}].steps must be a list")
            if len(steps) > 128:
                raise ValueError(f"macros[{i}] has {len(steps)} steps (max 128)")

        # stick
        stick = profile.get("stick")
        if stick is not None and not isinstance(stick, dict):
            raise ValueError("Profile 'stick' must be a dict or absent")

        # layers
        layers = profile.get("layers", [])
        if not isinstance(layers, list):
            raise ValueError("Profile 'layers' must be a list")

        # chords
        chords = profile.get("chords", [])
        if not isinstance(chords, list):
            raise ValueError("Profile 'chords' must be a list")

    # ------------------------------------------------------------------
    # Per-block binary encoders (private)
    # ------------------------------------------------------------------

    @staticmethod
    def _mode_to_u8(mode_str: str) -> int:
        """Convert a mapping mode string to its numeric ID."""
        _MAP = {
            "passthrough": 0, "disabled": 1, "disable": 1,
            "remap": 2, "macro": 3, "remap_hid": 4,
            "double_tap": 5, "turbo": 6,
            "sticky_mod": 7, "sticky": 7,
            "tap_hold": 8,
            "oneshot_mod": 9, "oneshot": 9,
            "auto_shift": 10, "mouse_button": 11,
            "gamepad_button": 17,
            "sequential": 12, "leader": 13,
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

    _CURVE_MAP: ClassVar[dict[str, int]] = {"linear": 0, "exponential": 1, "quadratic": 2}
    _SHAPE_MAP: ClassVar[dict[str, int]] = {"circle": 0, "square": 1, "octagon": 2}
    _SOCD_MAP: ClassVar[dict[str, int]] = {"neutral": 0, "last_input": 1, "first_input": 2}
    _RSTICK_MAP: ClassVar[dict[str, int]] = {"keys": 0, "mouse": 1, "scroll": 2}

    def _send_stick_block(self, slot: int, stick: dict) -> None:
        """Encode and send stick configuration.

        Binary format:
          deadzone:u16-LE  curve:u8  shape:u8  exp_x100:u8
          sensitivity:u16-LE  sprint_threshold:u16-LE
          sprint_multiplier:u16-LE (×100)
          socd_mode:u8  rt_activation:u8  rt_deactivation:u8
          right_stick_mode:u8  mouse_sensitivity:u8
          sprint_zone_enabled:u8
        """
        rapid = stick.get("rapid_trigger", {})
        buf = struct.pack("<HBBB HHH BBB BB B",
                          stick.get("deadzone", 400),
                          self._CURVE_MAP.get(stick.get("curve", "linear"), 0),
                          self._SHAPE_MAP.get(stick.get("shape", "circle"), 0),
                          min(int(stick.get("exp", 1.0) * 100), 255),
                          stick.get("sensitivity", 100),
                          stick.get("sprint_threshold", 0),
                          int(stick.get("sprint_multiplier", 1.0) * 100),
                          self._SOCD_MAP.get(stick.get("socd_mode", "neutral"), 0),
                          rapid.get("activation", 30),
                          rapid.get("deactivation", 20),
                          self._RSTICK_MAP.get(stick.get("right_stick_mode", "keys"), 0),
                          min(stick.get("mouse_sensitivity", 10), 255),
                          1 if stick.get("sprint_zone", {}).get("enabled", False) else 0)

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

    def _send_flick_stick_block(self, slot: int, flick: dict) -> None:
        """Encode and send flick stick configuration.

        Binary format:
          enabled:u8  threshold:u16-LE  snap_degrees:u16-LE
        """
        buf = struct.pack("<BHH",
                          1 if flick.get("enabled", False) else 0,
                          flick.get("threshold", 3000),
                          flick.get("snap_degrees", 0))
        self.send_config_block(CFG_BLOCK_FLICK_STICK, slot, buf)

    def _send_stick_accel_block(self, slot: int, saccel: dict) -> None:
        """Encode and send stick acceleration curve configuration.

        Binary format:
          type:u8  param:u16-LE
        """
        buf = struct.pack("<BH",
                          saccel.get("type", 0),
                          saccel.get("param", 200))
        self.send_config_block(CFG_BLOCK_STICK_ACCEL, slot, buf)

    def _rx_loop(self) -> None:
        if self._ser is None:
            return
        buffer = bytearray()
        _MAX_BUFFER = 65536  # 64 KB cap to prevent unbounded growth
        _MAX_LINE = 10240    # 10 KB max per NDJSON line

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

                    if len(raw_line) > _MAX_LINE:
                        log.warning(
                            "Dropping oversized line (%d bytes, max %d)",
                            len(raw_line), _MAX_LINE,
                        )
                        continue

                    raw = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    parsed = None
                    if raw.startswith("{") and raw.endswith("}"):
                        try:
                            parsed = json.loads(raw)
                        except Exception:
                            log.debug("JSON parse failed for line: %s", raw[:200])
                            parsed = None
                    self._record_history("rx", raw, parsed)
                    log.debug("Serial RX line: %s", self._trim_for_log(raw))
                    try:
                        self.rx.put_nowait(SerialLine(raw=raw, parsed=parsed))
                    except queue.Full:
                        # Drop oldest event to make room
                        with contextlib.suppress(queue.Empty):
                            self.rx.get_nowait()
                        with contextlib.suppress(queue.Full):
                            self.rx.put_nowait(SerialLine(raw=raw, parsed=parsed))
            else:
                time.sleep(0.01)

        log.info("Serial RX thread exiting")
