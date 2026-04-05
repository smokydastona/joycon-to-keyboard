from __future__ import annotations

import base64
import json
import tkinter as tk
import tkinter.ttk as ttk
import time
import zlib
from tkinter import filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText
from typing import Any, Dict, List, Optional

from serial.tools import list_ports

from .serial_client import SerialClient


def _ensure_profile_defaults(profile: dict) -> dict:
    if not isinstance(profile, dict):
        return {"ver": 1, "name": "default", "mappings": {}, "macros": [], "stick": {}}

    profile.setdefault("ver", 1)
    profile.setdefault("name", "default")
    profile.setdefault("mappings", {})
    profile.setdefault("macros", [])
    profile.setdefault("stick", {})

    if not isinstance(profile["mappings"], dict):
        profile["mappings"] = {}
    if not isinstance(profile["macros"], list):
        profile["macros"] = []
    if not isinstance(profile["stick"], dict):
        profile["stick"] = {}

    return profile


def _profile_to_share_code(profile: dict) -> str:
    payload = json.dumps(profile, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    compressed = zlib.compress(payload, level=9)
    token = base64.urlsafe_b64encode(compressed).decode("ascii")
    return f"JCB1:{token}"


def _share_code_to_profile(code: str) -> dict:
    code = code.strip()
    if not code.startswith("JCB1:"):
        raise ValueError("Invalid code prefix (expected JCB1:...)")
    token = code.split(":", 1)[1]
    compressed = base64.urlsafe_b64decode(token.encode("ascii"))
    payload = zlib.decompress(compressed)
    obj = json.loads(payload.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Decoded profile is not a JSON object")
    return obj


class OverlayWindow(tk.Toplevel):
    def __init__(self, parent: tk.Tk) -> None:
        super().__init__(parent)
        self.title("JoyCon Overlay")
        self.geometry("280x120")
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.92)
        except Exception:
            pass

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._closed = False
        self.slot_var = tk.StringVar(value="-")
        self.last_key_var = tk.StringVar(value="-")
        self.last_macro_var = tk.StringVar(value="-")

        frm = tk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(frm, text="JoyCon Bridge Overlay", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(frm, textvariable=self.slot_var).pack(anchor="w", pady=(6, 0))
        tk.Label(frm, textvariable=self.last_key_var).pack(anchor="w")
        tk.Label(frm, textvariable=self.last_macro_var).pack(anchor="w")

    def _on_close(self) -> None:
        self._closed = True
        try:
            self.destroy()
        except Exception:
            pass

    @property
    def is_closed(self) -> bool:
        return self._closed

    def set_slot(self, slot: int) -> None:
        self.slot_var.set(f"Active slot: {slot}")

    def set_last_key(self, pressed: bool, key_id: int) -> None:
        self.last_key_var.set(f"Key event: {'DOWN' if pressed else 'UP'}  key_id={key_id}")

    def set_macro(self, macro_id: str, state: str) -> None:
        self.last_macro_var.set(f"Macro: {macro_id}  ({state})")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("JoyCon Bridge Helper")
        self.geometry("980x680")

        self.client = SerialClient()

        self.port_var = tk.StringVar(value="")
        self.baud_var = tk.StringVar(value="115200")
        self.slot_var = tk.StringVar(value="0")

        self._overlay: Optional[OverlayWindow] = None

        self._recording = tk.BooleanVar(value=False)
        self._record_last_t: Optional[float] = None

        self._mapping_key_id = tk.StringVar(value="1")
        self._mapping_type = tk.StringVar(value="passthrough")
        self._mapping_remap_to = tk.StringVar(value="1")
        self._mapping_macro_id = tk.StringVar(value="")
        self._mapping_macro_pick = tk.StringVar(value="")

        self._stick_deadzone = tk.DoubleVar(value=0.15)
        self._stick_deadzone_shape = tk.StringVar(value="circle")
        self._stick_curve = tk.StringVar(value="linear")
        self._stick_curve_exp = tk.DoubleVar(value=1.0)

        self._bt_target_substr = tk.StringVar(value="Joy-Con")
        self._bt_target_preset = tk.StringVar(value="Either (Joy-Con)")
        self._bt_status = tk.StringVar(value="BT: -")

        # Track which sides are connected so the UI can reflect Left/Right/Both.
        # Keyed by BDA string when available.
        self._bt_conn_by_bda: Dict[str, str] = {}
        self._bt_connected_left = False
        self._bt_connected_right = False

        # Controller tab background banner widgets.
        self._bt_banner: Optional[tk.Frame] = None
        self._bt_banner_label: Optional[tk.Label] = None

        self._build_ui()
        self._refresh_ports()
        self.after(50, self._drain_rx)

    def _build_ui(self) -> None:
        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)

        tk.Label(top, text="Port:").pack(side=tk.LEFT)
        self.port_menu = tk.OptionMenu(top, self.port_var, "")
        self.port_menu.config(width=40)
        self.port_menu.pack(side=tk.LEFT, padx=(4, 8))

        tk.Button(top, text="Refresh", command=self._refresh_ports).pack(side=tk.LEFT)

        tk.Label(top, text="Baud:").pack(side=tk.LEFT, padx=(12, 0))
        tk.Entry(top, textvariable=self.baud_var, width=10).pack(side=tk.LEFT, padx=(4, 8))

        self.connect_btn = tk.Button(top, text="Connect", command=self._toggle_connect)
        self.connect_btn.pack(side=tk.LEFT)

        body = tk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        left = tk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = tk.Frame(body)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        # Tabs (left)
        self.tabs = ttk.Notebook(left)
        self.tabs.pack(fill=tk.BOTH, expand=True)

        self.tab_profile = tk.Frame(self.tabs)
        self.tab_macros = tk.Frame(self.tabs)
        self.tab_stick = tk.Frame(self.tabs)
        self.tab_share = tk.Frame(self.tabs)
        self.tab_overlay = tk.Frame(self.tabs)
        self.tab_controller = tk.Frame(self.tabs)

        self.tabs.add(self.tab_profile, text="Profile")
        self.tabs.add(self.tab_macros, text="Macros")
        self.tabs.add(self.tab_stick, text="Stick")
        self.tabs.add(self.tab_share, text="Share")
        self.tabs.add(self.tab_overlay, text="Overlay")
        self.tabs.add(self.tab_controller, text="Controller")

        self._build_profile_tab()
        self._build_macros_tab()
        self._build_stick_tab()
        self._build_share_tab()
        self._build_overlay_tab()
        self._build_controller_tab()

        # Log view (below tabs)
        tk.Label(left, text="Device log / events").pack(anchor="w", pady=(6, 0))
        self.log = ScrolledText(left, height=14, state="disabled")
        self.log.pack(fill=tk.BOTH, expand=False)

        # Right side controls
        tk.Label(right, text="Actions").pack(anchor="w")

        slot_row = tk.Frame(right)
        slot_row.pack(fill=tk.X, pady=(6, 0))
        tk.Label(slot_row, text="Slot:").pack(side=tk.LEFT)
        tk.OptionMenu(slot_row, self.slot_var, "0", "1", "2", "3").pack(side=tk.LEFT, padx=(6, 0))

        tk.Button(right, text="Ping", command=self._cmd_ping, width=22).pack(pady=(8, 0))
        tk.Button(right, text="Upload profile to slot", command=self._cmd_write_profile, width=22).pack(pady=(6, 0))
        tk.Button(right, text="Upload + Activate", command=self._cmd_upload_and_set_active, width=22).pack(pady=(6, 0))
        tk.Button(right, text="Read profile from slot", command=self._cmd_read_profile, width=22).pack(pady=(6, 0))
        tk.Button(right, text="Set active slot", command=self._cmd_set_active, width=22).pack(pady=(6, 0))

        tk.Label(right, text="Raw command (JSON line)").pack(anchor="w", pady=(14, 0))
        self.raw_entry = tk.Entry(right, width=30)
        self.raw_entry.pack(pady=(4, 0))
        tk.Button(right, text="Send", command=self._send_raw, width=22).pack(pady=(6, 0))

    def _build_profile_tab(self) -> None:
        tk.Label(self.tab_profile, text="Profile JSON").pack(anchor="w")
        self.profile_text = ScrolledText(self.tab_profile, height=18)
        self.profile_text.pack(fill=tk.BOTH, expand=True)

        initial = _ensure_profile_defaults({"name": "default"})
        self.profile_text.insert("1.0", json.dumps(initial, indent=2))

        prof_btns = tk.Frame(self.tab_profile)
        prof_btns.pack(fill=tk.X, pady=(6, 6))
        tk.Button(prof_btns, text="Load…", command=self._load_profile).pack(side=tk.LEFT)
        tk.Button(prof_btns, text="Save…", command=self._save_profile).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(prof_btns, text="Validate", command=self._validate_profile).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(prof_btns, text="Apply Stick→JSON", command=self._stick_apply_to_profile).pack(
            side=tk.LEFT, padx=(6, 0)
        )

    def _build_macros_tab(self) -> None:
        row = tk.Frame(self.tab_macros)
        row.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(row)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        right = tk.Frame(row)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        tk.Label(left, text="Macros").pack(anchor="w")
        self.macro_list = tk.Listbox(left, height=18, width=22)
        self.macro_list.pack(fill=tk.Y, expand=False)
        self.macro_list.bind("<<ListboxSelect>>", lambda _e: self._refresh_macro_steps())

        btns = tk.Frame(left)
        btns.pack(fill=tk.X, pady=(6, 0))
        tk.Button(btns, text="New", command=self._macro_new).pack(side=tk.LEFT)
        tk.Button(btns, text="Delete", command=self._macro_delete).pack(side=tk.LEFT, padx=(6, 0))
        tk.Checkbutton(left, text="Record mode", variable=self._recording).pack(anchor="w", pady=(10, 0))

        tk.Label(right, text="Steps").pack(anchor="w")
        self.step_list = tk.Listbox(right, height=14)
        self.step_list.pack(fill=tk.BOTH, expand=True)

        step_btns = tk.Frame(right)
        step_btns.pack(fill=tk.X, pady=(6, 0))
        tk.Button(step_btns, text="Add key step", command=self._step_add_key).pack(side=tk.LEFT)
        tk.Button(step_btns, text="Add delay", command=self._step_add_delay).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(step_btns, text="Delete step", command=self._step_delete).pack(side=tk.LEFT, padx=(6, 0))

        map_box = tk.LabelFrame(self.tab_macros, text="Input mapping (key_id → action)")
        map_box.pack(fill=tk.X, pady=(10, 0))

        r1 = tk.Frame(map_box)
        r1.pack(fill=tk.X, padx=8, pady=(6, 0))
        tk.Label(r1, text="Input key_id:").pack(side=tk.LEFT)
        tk.Entry(r1, textvariable=self._mapping_key_id, width=6).pack(side=tk.LEFT, padx=(6, 12))

        tk.Label(r1, text="Type:").pack(side=tk.LEFT)
        ttk.Combobox(
            r1,
            textvariable=self._mapping_type,
            values=["passthrough", "disable", "remap", "macro"],
            width=14,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 12))

        tk.Label(r1, text="Remap to:").pack(side=tk.LEFT)
        tk.Entry(r1, textvariable=self._mapping_remap_to, width=6).pack(side=tk.LEFT, padx=(6, 12))

        tk.Label(r1, text="Macro id:").pack(side=tk.LEFT)
        tk.Entry(r1, textvariable=self._mapping_macro_id, width=14).pack(side=tk.LEFT, padx=(6, 12))

        tk.Label(r1, text="Pick:").pack(side=tk.LEFT)
        self.macro_pick = ttk.Combobox(
            r1,
            textvariable=self._mapping_macro_pick,
            values=[],
            width=18,
            state="readonly",
        )
        self.macro_pick.pack(side=tk.LEFT, padx=(6, 12))
        self.macro_pick.bind("<<ComboboxSelected>>", lambda _e: self._mapping_pick_macro())

        tk.Button(r1, text="Apply", command=self._mapping_apply).pack(side=tk.LEFT)

        self._refresh_macro_list()

    def _build_stick_tab(self) -> None:
        info = tk.Label(
            self.tab_stick,
            text=(
                "These settings are stored in the profile for future use. "
                "They do not affect behavior yet until the UART protocol includes analog values."
            ),
            wraplength=900,
            justify="left",
        )
        info.pack(anchor="w", pady=(0, 8))

        row = tk.Frame(self.tab_stick)
        row.pack(fill=tk.X)

        tk.Label(row, text="Deadzone:").pack(side=tk.LEFT)
        tk.Scale(row, from_=0.0, to=0.5, resolution=0.01, orient="horizontal", variable=self._stick_deadzone).pack(
            side=tk.LEFT, padx=(6, 14)
        )

        tk.Label(row, text="Shape:").pack(side=tk.LEFT)
        ttk.Combobox(
            row,
            textvariable=self._stick_deadzone_shape,
            values=["circle", "square", "hybrid"],
            width=10,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 14))

        tk.Label(row, text="Curve:").pack(side=tk.LEFT)
        ttk.Combobox(
            row,
            textvariable=self._stick_curve,
            values=["linear", "exponential", "soft", "hard"],
            width=12,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 14))

        tk.Label(row, text="Exp:").pack(side=tk.LEFT)
        tk.Scale(row, from_=0.5, to=3.0, resolution=0.1, orient="horizontal", variable=self._stick_curve_exp).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        preview = tk.LabelFrame(self.tab_stick, text="Curve preview")
        preview.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.curve_canvas = tk.Canvas(preview, height=220)
        self.curve_canvas.pack(fill=tk.BOTH, expand=True)

        for var in (self._stick_deadzone, self._stick_deadzone_shape, self._stick_curve, self._stick_curve_exp):
            var.trace_add("write", lambda *_a: self._draw_curve_preview())
        self._draw_curve_preview()

    def _build_share_tab(self) -> None:
        tk.Label(self.tab_share, text="Profile share code").pack(anchor="w")
        self.share_text = ScrolledText(self.tab_share, height=10)
        self.share_text.pack(fill=tk.X)

        btns = tk.Frame(self.tab_share)
        btns.pack(fill=tk.X, pady=(6, 0))
        tk.Button(btns, text="Export from JSON", command=self._share_export).pack(side=tk.LEFT)
        tk.Button(btns, text="Import to JSON", command=self._share_import).pack(side=tk.LEFT, padx=(6, 0))

        tk.Label(
            self.tab_share,
            text=(
                "This is offline-only sharing: a compressed+encoded profile string. "
                "No network calls, no overlays/hooks, and nothing game-specific."
            ),
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

    def _build_overlay_tab(self) -> None:
        tk.Label(
            self.tab_overlay,
            text=(
                "Safe overlay: this is just an always-on-top window. "
                "No process hooking, no injection, no memory reads."
            ),
            wraplength=900,
            justify="left",
        ).pack(anchor="w")

        btns = tk.Frame(self.tab_overlay)
        btns.pack(fill=tk.X, pady=(10, 0))
        tk.Button(btns, text="Open overlay", command=self._overlay_open).pack(side=tk.LEFT)
        tk.Button(btns, text="Close overlay", command=self._overlay_close).pack(side=tk.LEFT, padx=(6, 0))

    def _build_controller_tab(self) -> None:
        # Connection background banner: left/right/both.
        self._bt_banner = tk.Frame(self.tab_controller, bg="#111f37")
        self._bt_banner.pack(fill=tk.X, padx=8, pady=(8, 0))
        self._bt_banner_label = tk.Label(
            self._bt_banner,
            textvariable=self._bt_status,
            bg="#111f37",
            fg="#e5e7eb",
            padx=10,
            pady=8,
            anchor="w",
        )
        self._bt_banner_label.pack(fill=tk.X)

        box = tk.LabelFrame(self.tab_controller, text="Controller connection")
        box.pack(fill=tk.X, padx=8, pady=8)

        row1 = tk.Frame(box)
        row1.pack(fill=tk.X, pady=(6, 0), padx=8)
        tk.Label(row1, text="Preset:").pack(side=tk.LEFT)
        preset = ttk.Combobox(
            row1,
            textvariable=self._bt_target_preset,
            values=["Either (Joy-Con)", "Left (Joy-Con (L))", "Right (Joy-Con (R))", "Both (Joy-Con (L+R))", "Custom"],
            width=20,
            state="readonly",
        )
        preset.pack(side=tk.LEFT, padx=(8, 12))
        preset.bind("<<ComboboxSelected>>", lambda _e: self._bt_apply_preset())

        tk.Label(row1, text="Target name contains:").pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=self._bt_target_substr, width=30).pack(side=tk.LEFT, padx=(8, 0))

        row2 = tk.Frame(box)
        row2.pack(fill=tk.X, pady=(10, 6), padx=8)
        tk.Button(row2, text="Connect / Scan", command=self._cmd_bt_connect, width=18).pack(side=tk.LEFT)
        # Status is shown in the banner above.

        note = (
            "This sends commands to the ESP32 BT host so you don't need to press buttons on the boards. "
            "Your controller may still need to be put into pairing mode (e.g. Joy-Con sync button)."
        )
        tk.Label(self.tab_controller, text=note, wraplength=900, justify="left").pack(anchor="w", padx=12, pady=(4, 0))

        self._update_bt_background()

    def _update_bt_background(self) -> None:
        if not self._bt_banner or not self._bt_banner_label:
            return

        # Theme-matched colors (see tools/generate_ui_bundle.py for the theme.json tokens)
        neutral_bg = "#111f37"
        neutral_fg = "#e5e7eb"
        left_bg = "#2b63ff"   # accent
        right_bg = "#22c55e"  # accent2
        both_bg = "#1f7ab8"   # blend-ish (kept in-family)

        if self._bt_connected_left and self._bt_connected_right:
            bg = both_bg
        elif self._bt_connected_left:
            bg = left_bg
        elif self._bt_connected_right:
            bg = right_bg
        else:
            bg = neutral_bg

        self._bt_banner.configure(bg=bg)
        self._bt_banner_label.configure(bg=bg, fg=neutral_fg)

    def _bt_apply_preset(self) -> None:
        p = self._bt_target_preset.get().strip()
        if p == "Either (Joy-Con)":
            self._bt_target_substr.set("Joy-Con")
        elif p == "Left (Joy-Con (L))":
            self._bt_target_substr.set("Joy-Con (L)")
        elif p == "Right (Joy-Con (R))":
            self._bt_target_substr.set("Joy-Con (R)")
        elif p == "Both (Joy-Con (L+R))":
            self._bt_target_substr.set("Joy-Con (")
        # Custom: leave the text box alone

    def _refresh_ports(self) -> None:
        ports = [p.device for p in list_ports.comports()]
        if not ports:
            ports = [""]

        menu = self.port_menu["menu"]
        menu.delete(0, "end")
        for p in ports:
            menu.add_command(label=p, command=lambda v=p: self.port_var.set(v))

        if self.port_var.get() not in ports:
            self.port_var.set(ports[0])

    def _toggle_connect(self) -> None:
        if self.client.is_connected:
            self.client.disconnect()
            self.connect_btn.config(text="Connect")
            self._log_line("[host] disconnected")
            return

        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("No port", "Select a COM port first")
            return

        try:
            baud = int(self.baud_var.get().strip())
        except ValueError:
            messagebox.showerror("Bad baud", "Baud must be an integer")
            return

        try:
            self.client.connect(port, baud)
        except Exception as e:
            messagebox.showerror("Connect failed", str(e))
            return

        self.connect_btn.config(text="Disconnect")
        self._log_line(f"[host] connected to {port} @ {baud}")

    def _validate_profile(self) -> dict:
        raw = self.profile_text.get("1.0", "end").strip()
        try:
            obj = json.loads(raw)
        except Exception as e:
            messagebox.showerror("Invalid JSON", str(e))
            raise
        return _ensure_profile_defaults(obj)

    def _set_profile_obj(self, obj: dict) -> None:
        obj = _ensure_profile_defaults(obj)
        self.profile_text.delete("1.0", "end")
        self.profile_text.insert("1.0", json.dumps(obj, indent=2, ensure_ascii=False))
        self._refresh_macro_list()
        self._stick_load_from_profile(obj)

    def _load_profile(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All files", "*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return
        self.profile_text.delete("1.0", "end")
        self.profile_text.insert("1.0", data)
        try:
            prof = self._validate_profile()
            self._refresh_macro_list()
            self._stick_load_from_profile(prof)
        except Exception:
            pass

    def _save_profile(self) -> None:
        try:
            self._validate_profile()
        except Exception:
            return

        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        data = self.profile_text.get("1.0", "end").strip() + "\n"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def _cmd_ping(self) -> None:
        self._send_cmd({"cmd": "ping"})

    def _cmd_bt_connect(self) -> None:
        target = self._bt_target_substr.get().strip()
        self._send_cmd({"cmd": "bt_set_target", "name_substr": target})
        both = (self._bt_target_preset.get().strip() == "Both (Joy-Con (L+R))")
        self._send_cmd({"cmd": "bt_connect", "both": both})

    def _cmd_upload_and_set_active(self) -> None:
        try:
            profile = self._validate_profile()
        except Exception:
            return
        slot = int(self.slot_var.get())
        self._send_cmd({"cmd": "write_profile", "slot": slot, "profile": profile})
        self._cmd_set_active()

    def _cmd_set_active(self) -> None:
        slot = int(self.slot_var.get())
        self._send_cmd({"cmd": "set_active_profile", "slot": slot})
        if self._overlay and not self._overlay.is_closed:
            self._overlay.set_slot(slot)

    def _cmd_write_profile(self) -> None:
        try:
            profile = self._validate_profile()
        except Exception:
            return
        self._send_cmd({"cmd": "write_profile", "slot": int(self.slot_var.get()), "profile": profile})

    def _cmd_read_profile(self) -> None:
        self._send_cmd({"cmd": "read_profile", "slot": int(self.slot_var.get())})

    def _send_raw(self) -> None:
        raw = self.raw_entry.get().strip()
        if not raw:
            return
        if raw.startswith("{"):
            try:
                obj = json.loads(raw)
            except Exception as e:
                messagebox.showerror("Invalid JSON", str(e))
                return
            self._send_cmd(obj)
        else:
            self._send_text(raw)

    def _send_cmd(self, obj: dict) -> None:
        try:
            self.client.send_obj(obj)
        except Exception as e:
            messagebox.showerror("Send failed", str(e))
            return
        self._log_line(f"[host->dev] {json.dumps(obj, ensure_ascii=False)}")

    def _send_text(self, text: str) -> None:
        try:
            self.client.send_text_line(text)
        except Exception as e:
            messagebox.showerror("Send failed", str(e))
            return
        self._log_line(f"[host->dev] {text}")

    def _drain_rx(self) -> None:
        try:
            while True:
                line = self.client.rx.get_nowait()
                if line.parsed is not None:
                    self._log_line(f"[dev] {json.dumps(line.parsed, ensure_ascii=False)}")
                    self._handle_dev_obj(line.parsed)
                else:
                    self._log_line(f"[dev] {line.raw}")
        except Exception:
            pass
        self.after(50, self._drain_rx)

    def _handle_dev_obj(self, obj: dict) -> None:
        evt = obj.get("evt")
        if evt == "mapped_key":
            try:
                pressed = bool(obj.get("pressed"))
                key_id = int(obj.get("key_id"))
            except Exception:
                return

            if self._overlay and not self._overlay.is_closed:
                self._overlay.set_last_key(pressed, key_id)

            if self._recording.get():
                self._record_macro_event(pressed, key_id)

        if evt == "macro":
            macro_id = str(obj.get("id", ""))
            state = str(obj.get("state", ""))
            if self._overlay and not self._overlay.is_closed:
                self._overlay.set_macro(macro_id, state)

        if evt == "bt_status":
            state = str(obj.get("state", "-"))
            name = obj.get("name")
            bda = obj.get("bda")

            suffix = ""
            if isinstance(name, str) and name:
                suffix += f"  name={name}"
            if isinstance(bda, str) and bda:
                suffix += f"  bda={bda}"
            self._bt_status.set(f"BT: {state}{suffix}")

            # Track side connectivity by BDA to drive the background.
            def _side_from_name(n: object) -> Optional[str]:
                if not isinstance(n, str):
                    return None
                if "(L)" in n:
                    return "L"
                if "(R)" in n:
                    return "R"
                return None

            if state == "connected":
                side = _side_from_name(name)
                if side is None:
                    # If we don't know, assume left unless left is already taken.
                    side = "R" if self._bt_connected_left and not self._bt_connected_right else "L"

                if isinstance(bda, str) and bda:
                    self._bt_conn_by_bda[bda] = side

                if side == "L":
                    self._bt_connected_left = True
                elif side == "R":
                    self._bt_connected_right = True

            elif state == "disconnected":
                side = None
                if isinstance(bda, str) and bda:
                    side = self._bt_conn_by_bda.pop(bda, None)

                if side == "L":
                    self._bt_connected_left = False
                elif side == "R":
                    self._bt_connected_right = False
                else:
                    # Unknown disconnect (no bda): clear both.
                    self._bt_connected_left = False
                    self._bt_connected_right = False

            self._update_bt_background()

    def _current_profile(self) -> dict:
        return self._validate_profile()

    def _macros(self) -> List[Dict[str, Any]]:
        prof = self._current_profile()
        macros = prof.get("macros", [])
        return macros if isinstance(macros, list) else []

    def _refresh_macro_list(self) -> None:
        try:
            macros = self._macros()
        except Exception:
            macros = []

        self.macro_list.delete(0, "end")
        ids: List[str] = []
        for m in macros:
            mid = m.get("id")
            if isinstance(mid, str) and mid:
                self.macro_list.insert("end", mid)
                ids.append(mid)

        if hasattr(self, "macro_pick"):
            try:
                self.macro_pick["values"] = ids
            except Exception:
                pass
            if ids and self._mapping_macro_pick.get() not in ids:
                self._mapping_macro_pick.set(ids[0])

        if self.macro_list.size() > 0 and not self.macro_list.curselection():
            self.macro_list.selection_set(0)
        self._refresh_macro_steps()

    def _mapping_pick_macro(self) -> None:
        picked = self._mapping_macro_pick.get().strip()
        if picked:
            self._mapping_macro_id.set(picked)

    def _selected_macro_index(self) -> Optional[int]:
        sel = self.macro_list.curselection()
        if not sel:
            return None
        return int(sel[0])

    def _refresh_macro_steps(self) -> None:
        self.step_list.delete(0, "end")
        idx = self._selected_macro_index()
        if idx is None:
            return

        macros = self._macros()
        if idx < 0 or idx >= len(macros):
            return

        steps = macros[idx].get("steps", [])
        if not isinstance(steps, list):
            return

        for st in steps:
            if not isinstance(st, dict):
                continue
            t = st.get("type")
            if t == "delay":
                self.step_list.insert("end", f"delay {st.get('ms', 0)}ms")
            elif t == "key":
                self.step_list.insert(
                    "end",
                    f"key key_id={st.get('key_id')} {'DOWN' if st.get('pressed') else 'UP'}",
                )
            else:
                self.step_list.insert("end", f"(unknown) {st}")

    def _macro_new(self) -> None:
        try:
            prof = self._current_profile()
        except Exception:
            return

        new_id = f"macro{int(time.time())}"
        prof["macros"].append({"id": new_id, "steps": []})
        self._set_profile_obj(prof)

        self.macro_list.selection_clear(0, "end")
        self.macro_list.selection_set(self.macro_list.size() - 1)
        self._refresh_macro_steps()

    def _macro_delete(self) -> None:
        idx = self._selected_macro_index()
        if idx is None:
            return

        try:
            prof = self._current_profile()
        except Exception:
            return

        macros = prof.get("macros", [])
        if not isinstance(macros, list) or idx >= len(macros):
            return

        del macros[idx]
        prof["macros"] = macros
        self._set_profile_obj(prof)

    def _step_add_key(self) -> None:
        idx = self._selected_macro_index()
        if idx is None:
            messagebox.showerror("No macro", "Select a macro first")
            return

        try:
            key_id = int(self._mapping_key_id.get())
        except ValueError:
            messagebox.showerror("Bad key_id", "Input key_id must be an integer")
            return

        try:
            prof = self._current_profile()
        except Exception:
            return

        prof["macros"][idx].setdefault("steps", []).append({"type": "key", "key_id": key_id, "pressed": True})
        prof["macros"][idx]["steps"].append({"type": "key", "key_id": key_id, "pressed": False})
        self._set_profile_obj(prof)

    def _step_add_delay(self) -> None:
        idx = self._selected_macro_index()
        if idx is None:
            messagebox.showerror("No macro", "Select a macro first")
            return

        ms = simpledialog.askinteger("Delay", "Delay in ms:", initialvalue=50, minvalue=0, maxvalue=5000)
        if ms is None:
            return

        try:
            prof = self._current_profile()
        except Exception:
            return

        prof["macros"][idx].setdefault("steps", []).append({"type": "delay", "ms": int(ms)})
        self._set_profile_obj(prof)

    def _step_delete(self) -> None:
        midx = self._selected_macro_index()
        if midx is None:
            return
        sel = self.step_list.curselection()
        if not sel:
            return
        sidx = int(sel[0])

        try:
            prof = self._current_profile()
        except Exception:
            return

        steps = prof["macros"][midx].get("steps", [])
        if not isinstance(steps, list) or sidx >= len(steps):
            return
        del steps[sidx]
        prof["macros"][midx]["steps"] = steps
        self._set_profile_obj(prof)

    def _record_macro_event(self, pressed: bool, key_id: int) -> None:
        idx = self._selected_macro_index()
        if idx is None:
            return

        now = time.time()
        if self._record_last_t is not None:
            dt_ms = int((now - self._record_last_t) * 1000.0)
        else:
            dt_ms = 0
        self._record_last_t = now

        try:
            prof = self._current_profile()
        except Exception:
            return

        steps = prof["macros"][idx].setdefault("steps", [])
        if dt_ms > 0:
            steps.append({"type": "delay", "ms": min(dt_ms, 5000)})
        # Macro step key_ids are output-space (0..127). When key_id is in the
        # right-side input namespace (128..255), record the base id.
        rec_key_id = int(key_id)
        if rec_key_id >= 128:
            rec_key_id -= 128
        steps.append({"type": "key", "key_id": rec_key_id, "pressed": bool(pressed)})
        self._set_profile_obj(prof)

    def _mapping_apply(self) -> None:
        try:
            in_id = int(self._mapping_key_id.get())
        except ValueError:
            messagebox.showerror("Bad key_id", "Input key_id must be an integer")
            return
        if in_id < 0 or in_id > 255:
            messagebox.showerror("Bad key_id", "Input key_id must be 0..255")
            return

        mtype = self._mapping_type.get()

        try:
            prof = self._current_profile()
        except Exception:
            return

        mappings = prof.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
            prof["mappings"] = mappings

        key = str(in_id)
        if mtype == "passthrough":
            mappings.pop(key, None)
        elif mtype == "disable":
            mappings[key] = {"type": "disable"}
        elif mtype == "remap":
            try:
                to = int(self._mapping_remap_to.get())
            except ValueError:
                messagebox.showerror("Bad remap", "Remap-to must be an integer")
                return
            if to < 0 or to > 127:
                messagebox.showerror("Bad remap", "Remap-to must be 0..127")
                return
            mappings[key] = {"type": "remap", "to": to}
        elif mtype == "macro":
            macro_id = self._mapping_macro_id.get().strip()
            if not macro_id:
                messagebox.showerror("Bad macro", "Macro id is required")
                return
            mappings[key] = {"type": "macro", "id": macro_id}

        self._set_profile_obj(prof)

    def _share_export(self) -> None:
        try:
            prof = self._current_profile()
        except Exception:
            return
        code = _profile_to_share_code(prof)
        self.share_text.delete("1.0", "end")
        self.share_text.insert("1.0", code)

    def _share_import(self) -> None:
        code = self.share_text.get("1.0", "end").strip()
        if not code:
            return
        try:
            prof = _share_code_to_profile(code)
        except Exception as e:
            messagebox.showerror("Import failed", str(e))
            return
        self._set_profile_obj(prof)

    def _overlay_open(self) -> None:
        if self._overlay and not self._overlay.is_closed:
            try:
                self._overlay.lift()
            except Exception:
                pass
            return
        self._overlay = OverlayWindow(self)
        try:
            self._overlay.set_slot(int(self.slot_var.get()))
        except Exception:
            pass

    def _overlay_close(self) -> None:
        if not self._overlay:
            return
        try:
            self._overlay.destroy()
        except Exception:
            pass
        self._overlay = None

    def _stick_load_from_profile(self, prof: dict) -> None:
        stick = prof.get("stick", {})
        if not isinstance(stick, dict):
            return
        dz = stick.get("deadzone")
        if isinstance(dz, (int, float)):
            self._stick_deadzone.set(float(dz))
        shape = stick.get("shape")
        if isinstance(shape, str):
            self._stick_deadzone_shape.set(shape)
        curve = stick.get("curve")
        if isinstance(curve, str):
            self._stick_curve.set(curve)
        exp = stick.get("exp")
        if isinstance(exp, (int, float)):
            self._stick_curve_exp.set(float(exp))

    def _stick_apply_to_profile(self) -> None:
        try:
            prof = self._current_profile()
        except Exception:
            return
        stick = prof.setdefault("stick", {})
        if not isinstance(stick, dict):
            stick = {}
            prof["stick"] = stick

        stick["deadzone"] = round(float(self._stick_deadzone.get()), 3)
        stick["shape"] = str(self._stick_deadzone_shape.get())
        stick["curve"] = str(self._stick_curve.get())
        stick["exp"] = round(float(self._stick_curve_exp.get()), 3)

        self._set_profile_obj(prof)

    def _draw_curve_preview(self) -> None:
        c = self.curve_canvas
        c.delete("all")

        w = max(c.winfo_width(), 320)
        h = max(c.winfo_height(), 220)
        pad = 20

        # axes
        c.create_line(pad, h - pad, w - pad, h - pad)
        c.create_line(pad, h - pad, pad, pad)

        deadzone = float(self._stick_deadzone.get())
        curve = self._stick_curve.get()
        exp = float(self._stick_curve_exp.get())

        def f(x: float) -> float:
            # x in [0,1]
            if x <= deadzone:
                return 0.0
            xn = (x - deadzone) / max(1e-6, (1.0 - deadzone))
            if curve == "linear":
                y = xn
            elif curve == "exponential":
                y = xn**exp
            elif curve == "soft":
                y = xn ** max(0.8, exp * 0.7)
            elif curve == "hard":
                y = xn ** max(1.2, exp * 1.3)
            else:
                y = xn
            return max(0.0, min(1.0, y))

        pts = []
        for i in range(0, 101):
            x = i / 100.0
            y = f(x)
            px = pad + x * (w - 2 * pad)
            py = (h - pad) - y * (h - 2 * pad)
            pts.append((px, py))

        for i in range(1, len(pts)):
            c.create_line(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])

    def _log_line(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> None:
    try:
        app = App()
    except Exception as e:
        messagebox.showerror("Startup failed", str(e))
        raise
    app.mainloop()
