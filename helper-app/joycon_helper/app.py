from __future__ import annotations

import base64
import json
import math
import sys
import tkinter as tk
import tkinter.ttk as ttk
import time
import zlib
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText
from typing import Any, Dict, List, Optional, Tuple

from serial.tools import list_ports

from .serial_client import SerialClient


DEFAULT_UI_THEME: dict = {
    "name": "sketchbook-ink",
    "version": 1,
    "colors": {
        "bg": "#e8d8b8",
        "panel": "#f2e8d0",
        "panel2": "#e2d0a8",
        "text": "#2a1f0e",
        "muted": "#6b5d48",
        "border": "#b09878",
        "accent": "#2f4a9e",
        "accent2": "#2b6a4b",
        "danger": "#b42318",
        "warning": "#a16207",
    },
    "typography": {
        # Sketch font matching Joy-Con overlay style. Tkinter falls back to system font if unavailable.
        "font_family": "Segoe Print",
        "font_size": 10,
        "mono_family": "Consolas",
        "mono_size": 10,
    },
    "spacing": {"xs": 4, "sm": 8, "md": 12, "lg": 16},
    "radii": {"sm": 6, "md": 10, "lg": 14},
}


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"bad hex color: {h!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend_hex(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, float(t)))
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    rr = int(ar + (br - ar) * t)
    rg = int(ag + (bg - ag) * t)
    rb = int(ab + (bb - ab) * t)
    return _rgb_to_hex((rr, rg, rb))


def _relative_luma(h: str) -> float:
    # Rough relative luminance in [0,1] for contrast decisions.
    r, g, b = _hex_to_rgb(h)
    return (0.2126 * (r / 255.0)) + (0.7152 * (g / 255.0)) + (0.0722 * (b / 255.0))


def _contrast_on(bg: str) -> str:
    # Choose an ink/light color that will read on bg.
    return "#111111" if _relative_luma(bg) > 0.6 else "#fff6e1"


def _load_theme_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("theme.json must be a JSON object")
    if not isinstance(obj.get("colors"), dict) or not isinstance(obj.get("typography"), dict):
        raise ValueError("theme.json missing required keys")
    return obj


def _frozen_bundle_root() -> Optional[Path]:
    base = getattr(sys, "_MEIPASS", None)
    if not isinstance(base, str) or not base:
        return None
    try:
        return Path(base).resolve()
    except Exception:
        return None


def _executable_dir() -> Optional[Path]:
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve().parent
    except Exception:
        return None


def _dedupe_paths(paths: List[Path]) -> List[Path]:
    seen: set[str] = set()
    unique: List[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _ui_bundle_search_roots() -> List[Path]:
    roots: List[Path] = []
    try:
        roots.append(Path.cwd() / ".ui-bundle")
    except Exception:
        pass

    exe_dir = _executable_dir()
    if exe_dir is not None:
        roots.append(exe_dir / ".ui-bundle")

    bundle_root = _frozen_bundle_root()
    if bundle_root is not None:
        roots.append(bundle_root / ".ui-bundle")

    here = Path(__file__).resolve()
    roots.extend(
        [
            here.parents[1] / ".ui-bundle",  # helper-app/.ui-bundle
            here.parents[3] / ".ui-bundle",  # repo root/.ui-bundle
        ]
    )
    return _dedupe_paths(roots)


def _joycons_search_roots() -> List[Path]:
    roots: List[Path] = []
    try:
        roots.extend(
            [
                Path.cwd(),
                Path.cwd() / ".ui-bundle",
                Path.cwd() / "docs" / "ui" / "assets",
            ]
        )
    except Exception:
        pass

    exe_dir = _executable_dir()
    if exe_dir is not None:
        roots.extend([exe_dir, exe_dir / ".ui-bundle"])

    bundle_root = _frozen_bundle_root()
    if bundle_root is not None:
        roots.extend([bundle_root, bundle_root / ".ui-bundle"])

    here = Path(__file__).resolve()
    roots.extend(
        [
            here.parents[1],  # helper-app/
            here.parents[1] / ".ui-bundle",  # helper-app/.ui-bundle/
            here.parents[3],  # repo root/
            here.parents[3] / ".ui-bundle",  # repo root/.ui-bundle/
            here.parents[3] / "docs" / "ui" / "assets",  # repo root/docs/ui/assets/
        ]
    )
    return _dedupe_paths(roots)


def _ensure_profile_defaults(profile: dict) -> dict:
    if not isinstance(profile, dict):
        return {"ver": 1, "name": "default", "mappings": {}, "macros": [], "stick": {}, "ui": {"hotspots": {}}}

    profile.setdefault("ver", 1)
    profile.setdefault("name", "default")
    profile.setdefault("mappings", {})
    profile.setdefault("macros", [])
    profile.setdefault("stick", {})
    profile.setdefault("ui", {"hotspots": {}})

    if not isinstance(profile["mappings"], dict):
        profile["mappings"] = {}
    if not isinstance(profile["macros"], list):
        profile["macros"] = []
    if not isinstance(profile["stick"], dict):
        profile["stick"] = {}

    if not isinstance(profile.get("ui"), dict):
        profile["ui"] = {"hotspots": {}}
    profile["ui"].setdefault("hotspots", {})
    if not isinstance(profile["ui"].get("hotspots"), dict):
        profile["ui"]["hotspots"] = {}

    return profile


JOYCONS_IMAGE_W = 1536
JOYCONS_IMAGE_H = 1024
JOYCONS_IMAGE_STATE_NAMES = ("none", "left", "right", "both")

# Normalized hotspot positions over joycons.png.
# These are intentionally approximate: the recommended flow is to use Learn
# to bind each physical control to its observed input key_id.
KEYMAP_HOTSPOTS: List[Tuple[str, float, float]] = [
    ("ZL", 420 / JOYCONS_IMAGE_W, 150 / JOYCONS_IMAGE_H),
    ("ZR", 1115 / JOYCONS_IMAGE_W, 150 / JOYCONS_IMAGE_H),
    ("-", 420 / JOYCONS_IMAGE_W, 335 / JOYCONS_IMAGE_H),
    ("+", 1110 / JOYCONS_IMAGE_W, 335 / JOYCONS_IMAGE_H),
    ("CAP", 395 / JOYCONS_IMAGE_W, 720 / JOYCONS_IMAGE_H),
    ("HOME", 1140 / JOYCONS_IMAGE_W, 720 / JOYCONS_IMAGE_H),
    ("LSTK", 250 / JOYCONS_IMAGE_W, 435 / JOYCONS_IMAGE_H),
    ("D-UP", 300 / JOYCONS_IMAGE_W, 545 / JOYCONS_IMAGE_H),
    ("D-DN", 300 / JOYCONS_IMAGE_W, 665 / JOYCONS_IMAGE_H),
    ("D-L", 225 / JOYCONS_IMAGE_W, 605 / JOYCONS_IMAGE_H),
    ("D-R", 375 / JOYCONS_IMAGE_W, 605 / JOYCONS_IMAGE_H),
    ("A", 1330 / JOYCONS_IMAGE_W, 460 / JOYCONS_IMAGE_H),
    ("B", 1260 / JOYCONS_IMAGE_W, 535 / JOYCONS_IMAGE_H),
    ("X", 1260 / JOYCONS_IMAGE_W, 385 / JOYCONS_IMAGE_H),
    ("Y", 1190 / JOYCONS_IMAGE_W, 460 / JOYCONS_IMAGE_H),
    ("RSTK", 1260 / JOYCONS_IMAGE_W, 605 / JOYCONS_IMAGE_H),
]


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
    def __init__(self, parent: tk.Tk, theme: Optional[dict] = None) -> None:
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

        colors = (theme or DEFAULT_UI_THEME).get("colors", DEFAULT_UI_THEME["colors"])
        typo = (theme or DEFAULT_UI_THEME).get("typography", DEFAULT_UI_THEME["typography"])

        self.configure(bg=colors["bg"])

        frm = tk.Frame(self, bg=colors["bg"])
        frm.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tk.Label(
            frm,
            text="JoyCon Bridge Overlay",
            font=(typo.get("font_family", "Segoe UI"), 11, "bold"),
            bg=colors["bg"],
            fg=colors["text"],
        ).pack(anchor="w")
        tk.Label(frm, textvariable=self.slot_var, bg=colors["bg"], fg=colors["text"]).pack(anchor="w", pady=(6, 0))
        tk.Label(frm, textvariable=self.last_key_var, bg=colors["bg"], fg=colors["text"]).pack(anchor="w")
        tk.Label(frm, textvariable=self.last_macro_var, bg=colors["bg"], fg=colors["text"]).pack(anchor="w")

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

        self._ui_theme = self._load_ui_theme()
        self._colors = self._ui_theme.get("colors", DEFAULT_UI_THEME["colors"])
        self._typo = self._ui_theme.get("typography", DEFAULT_UI_THEME["typography"])

        self._apply_ttk_theme()

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

        # Keymap editor (Controller tab)
        self._keymap_status = tk.StringVar(value="Click a control to select it. Use Learn to bind its key_id.")
        self._keymap_selected_name: Optional[str] = None
        self._keymap_learn_name: Optional[str] = None
        self._keymap_canvas: Optional[tk.Canvas] = None
        self._keymap_img_state = "none"
        self._keymap_img_paths: Dict[str, Path] = {}
        self._keymap_img_path: Optional[Path] = None
        self._keymap_img_base: Optional[tk.PhotoImage] = None
        self._keymap_img_scaled: Optional[tk.PhotoImage] = None
        self._keymap_hotspot_px: Dict[str, Tuple[float, float]] = {}

        self._build_ui()
        self._apply_widget_theme()
        self._refresh_ports()
        self.after(50, self._drain_rx)

    def _load_ui_theme(self) -> dict:
        # Load a local UI bundle theme if present; otherwise use defaults.
        candidates = [root / "theme.json" for root in _ui_bundle_search_roots()]

        for c in candidates:
            try:
                if c.exists():
                    return _load_theme_json(c)
            except Exception:
                continue

        return DEFAULT_UI_THEME

    def _apply_ttk_theme(self) -> None:
        colors = self._colors
        typo = self._typo

        try:
            self.configure(bg=colors["bg"])
        except Exception:
            pass

        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except Exception:
            pass

        base_font = (typo.get("font_family", "Segoe UI"), int(typo.get("font_size", 10)))

        style.configure("TFrame", background=colors["bg"])
        style.configure("TLabel", background=colors["bg"], foreground=colors["text"], font=base_font)
        style.configure("Muted.TLabel", background=colors["bg"], foreground=colors["muted"], font=base_font)

        # Inputs
        style.configure(
            "TEntry",
            padding=(6, 4),
        )
        style.configure("TCombobox", padding=(6, 3))

        # Buttons
        style.configure("TButton", padding=(10, 6), font=base_font)
        style.configure("Primary.TButton", padding=(10, 6), font=base_font)

        # Notebook
        try:
            style.configure("TNotebook", background=colors["bg"], borderwidth=0)
            style.configure("TNotebook.Tab", padding=(10, 6))
        except Exception:
            pass

    def _theme_scrolled_text(self, w: ScrolledText) -> None:
        colors = self._colors
        typo = self._typo
        sel_fg = _contrast_on(colors.get("accent", "#2f4a9e"))
        try:
            w.configure(
                bg=colors["panel2"],
                fg=colors["text"],
                insertbackground=colors["text"],
                selectbackground=colors["accent"],
                selectforeground=sel_fg,
                highlightthickness=1,
                highlightbackground=colors["border"],
                highlightcolor=colors["accent"],
                font=(typo.get("mono_family", "Consolas"), int(typo.get("mono_size", 10))),
            )
        except Exception:
            pass

    def _theme_listbox(self, w: tk.Listbox) -> None:
        colors = self._colors
        typo = self._typo
        sel_fg = _contrast_on(colors.get("accent", "#2f4a9e"))
        try:
            w.configure(
                bg=colors["panel2"],
                fg=colors["text"],
                selectbackground=colors["accent"],
                selectforeground=sel_fg,
                highlightthickness=1,
                highlightbackground=colors["border"],
                highlightcolor=colors["accent"],
                font=(typo.get("mono_family", "Consolas"), int(typo.get("mono_size", 10))),
            )
        except Exception:
            pass

    def _apply_widget_theme(self) -> None:
        # Apply token colors to widgets that are not ttk-styled.
        try:
            self._theme_scrolled_text(self.log)
        except Exception:
            pass
        for maybe in ("profile_text", "share_text"):
            w = getattr(self, maybe, None)
            if isinstance(w, ScrolledText):
                self._theme_scrolled_text(w)

        for maybe in ("macro_list", "step_list"):
            w = getattr(self, maybe, None)
            if isinstance(w, tk.Listbox):
                self._theme_listbox(w)

        # Curve canvas
        if hasattr(self, "curve_canvas") and isinstance(self.curve_canvas, tk.Canvas):
            try:
                self.curve_canvas.configure(
                    bg=self._colors["panel2"],
                    highlightthickness=1,
                    highlightbackground=self._colors["border"],
                    highlightcolor=self._colors["accent"],
                )
            except Exception:
                pass

    def _build_ui(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(top, text="Port:").pack(side=tk.LEFT)
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, values=[], width=40, state="readonly")
        self.port_combo.pack(side=tk.LEFT, padx=(4, 8))

        ttk.Button(top, text="Refresh", command=self._refresh_ports).pack(side=tk.LEFT)

        ttk.Label(top, text="Baud:").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Entry(top, textvariable=self.baud_var, width=10).pack(side=tk.LEFT, padx=(4, 8))

        self.connect_btn = ttk.Button(top, text="Connect", command=self._toggle_connect)
        self.connect_btn.pack(side=tk.LEFT)

        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(body)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        # Tabs (left)
        self.tabs = ttk.Notebook(left)
        self.tabs.pack(fill=tk.BOTH, expand=True)

        self.tab_profile = ttk.Frame(self.tabs)
        self.tab_macros = ttk.Frame(self.tabs)
        self.tab_stick = ttk.Frame(self.tabs)
        self.tab_share = ttk.Frame(self.tabs)
        self.tab_overlay = ttk.Frame(self.tabs)
        self.tab_controller = ttk.Frame(self.tabs)

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
        ttk.Label(left, text="Device log / events").pack(anchor="w", pady=(6, 0))
        self.log = ScrolledText(left, height=14, state="disabled")
        self.log.pack(fill=tk.BOTH, expand=False)

        # Right side controls
        ttk.Label(right, text="Actions").pack(anchor="w")

        slot_row = ttk.Frame(right)
        slot_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(slot_row, text="Slot:").pack(side=tk.LEFT)
        self.slot_combo = ttk.Combobox(slot_row, textvariable=self.slot_var, values=["0", "1", "2", "3"], width=4, state="readonly")
        self.slot_combo.pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(right, text="Ping", command=self._cmd_ping, width=22).pack(pady=(8, 0))
        ttk.Button(right, text="Upload profile to slot", command=self._cmd_write_profile, width=22).pack(pady=(6, 0))
        ttk.Button(right, text="Upload + Activate", command=self._cmd_upload_and_set_active, width=22).pack(pady=(6, 0))
        ttk.Button(right, text="Read profile from slot", command=self._cmd_read_profile, width=22).pack(pady=(6, 0))
        ttk.Button(right, text="Set active slot", command=self._cmd_set_active, width=22).pack(pady=(6, 0))

        ttk.Label(right, text="Raw command (JSON line)").pack(anchor="w", pady=(14, 0))
        self.raw_entry = ttk.Entry(right, width=30)
        self.raw_entry.pack(pady=(4, 0))
        ttk.Button(right, text="Send", command=self._send_raw, width=22).pack(pady=(6, 0))

    def _build_profile_tab(self) -> None:
        ttk.Label(self.tab_profile, text="Profile JSON").pack(anchor="w")
        self.profile_text = ScrolledText(self.tab_profile, height=18)
        self.profile_text.pack(fill=tk.BOTH, expand=True)
        self._theme_scrolled_text(self.profile_text)

        initial = _ensure_profile_defaults({"name": "default"})
        self.profile_text.insert("1.0", json.dumps(initial, indent=2))

        prof_btns = ttk.Frame(self.tab_profile)
        prof_btns.pack(fill=tk.X, pady=(6, 6))
        ttk.Button(prof_btns, text="Load…", command=self._load_profile).pack(side=tk.LEFT)
        ttk.Button(prof_btns, text="Save…", command=self._save_profile).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(prof_btns, text="Validate", command=self._validate_profile).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(prof_btns, text="Apply Stick→JSON", command=self._stick_apply_to_profile).pack(
            side=tk.LEFT, padx=(6, 0)
        )

    def _build_macros_tab(self) -> None:
        row = ttk.Frame(self.tab_macros)
        row.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(row)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))

        right = ttk.Frame(row)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(left, text="Macros").pack(anchor="w")
        self.macro_list = tk.Listbox(left, height=18, width=22)
        self.macro_list.pack(fill=tk.Y, expand=False)
        self.macro_list.bind("<<ListboxSelect>>", lambda _e: self._refresh_macro_steps())
        self._theme_listbox(self.macro_list)

        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btns, text="New", command=self._macro_new).pack(side=tk.LEFT)
        ttk.Button(btns, text="Delete", command=self._macro_delete).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Checkbutton(left, text="Record mode", variable=self._recording).pack(anchor="w", pady=(10, 0))

        ttk.Label(right, text="Steps").pack(anchor="w")
        self.step_list = tk.Listbox(right, height=14)
        self.step_list.pack(fill=tk.BOTH, expand=True)
        self._theme_listbox(self.step_list)

        step_btns = ttk.Frame(right)
        step_btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(step_btns, text="Add key step", command=self._step_add_key).pack(side=tk.LEFT)
        ttk.Button(step_btns, text="Add delay", command=self._step_add_delay).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(step_btns, text="Delete step", command=self._step_delete).pack(side=tk.LEFT, padx=(6, 0))

        map_box = ttk.LabelFrame(self.tab_macros, text="Input mapping (key_id → action)")
        map_box.pack(fill=tk.X, pady=(10, 0))

        r1 = ttk.Frame(map_box)
        r1.pack(fill=tk.X, padx=8, pady=(6, 0))
        ttk.Label(r1, text="Input key_id:").pack(side=tk.LEFT)
        ttk.Entry(r1, textvariable=self._mapping_key_id, width=6).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r1, text="Type:").pack(side=tk.LEFT)
        ttk.Combobox(
            r1,
            textvariable=self._mapping_type,
            values=["passthrough", "disable", "remap", "macro"],
            width=14,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r1, text="Remap to:").pack(side=tk.LEFT)
        ttk.Entry(r1, textvariable=self._mapping_remap_to, width=6).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r1, text="Macro id:").pack(side=tk.LEFT)
        ttk.Entry(r1, textvariable=self._mapping_macro_id, width=14).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r1, text="Pick:").pack(side=tk.LEFT)
        self.macro_pick = ttk.Combobox(
            r1,
            textvariable=self._mapping_macro_pick,
            values=[],
            width=18,
            state="readonly",
        )
        self.macro_pick.pack(side=tk.LEFT, padx=(6, 12))
        self.macro_pick.bind("<<ComboboxSelected>>", lambda _e: self._mapping_pick_macro())

        ttk.Button(r1, text="Apply", command=self._mapping_apply).pack(side=tk.LEFT)

        self._refresh_macro_list()

    def _build_stick_tab(self) -> None:
        info = ttk.Label(
            self.tab_stick,
            text=(
                "These settings are stored in the profile for future use. "
                "They do not affect behavior yet until the UART protocol includes analog values."
            ),
            wraplength=900,
            justify="left",
        )
        info.pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(self.tab_stick)
        row.pack(fill=tk.X)

        ttk.Label(row, text="Deadzone:").pack(side=tk.LEFT)
        tk.Scale(row, from_=0.0, to=0.5, resolution=0.01, orient="horizontal", variable=self._stick_deadzone).pack(
            side=tk.LEFT, padx=(6, 14)
        )

        ttk.Label(row, text="Shape:").pack(side=tk.LEFT)
        ttk.Combobox(
            row,
            textvariable=self._stick_deadzone_shape,
            values=["circle", "square", "hybrid"],
            width=10,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 14))

        ttk.Label(row, text="Curve:").pack(side=tk.LEFT)
        ttk.Combobox(
            row,
            textvariable=self._stick_curve,
            values=["linear", "exponential", "soft", "hard"],
            width=12,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 14))

        ttk.Label(row, text="Exp:").pack(side=tk.LEFT)
        tk.Scale(row, from_=0.5, to=3.0, resolution=0.1, orient="horizontal", variable=self._stick_curve_exp).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        preview = ttk.LabelFrame(self.tab_stick, text="Curve preview")
        preview.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.curve_canvas = tk.Canvas(preview, height=220)
        self.curve_canvas.pack(fill=tk.BOTH, expand=True)
        try:
            self.curve_canvas.configure(bg=self._colors["panel2"])
        except Exception:
            pass

        for var in (self._stick_deadzone, self._stick_deadzone_shape, self._stick_curve, self._stick_curve_exp):
            var.trace_add("write", lambda *_a: self._draw_curve_preview())
        self._draw_curve_preview()

    def _build_share_tab(self) -> None:
        ttk.Label(self.tab_share, text="Profile share code").pack(anchor="w")
        self.share_text = ScrolledText(self.tab_share, height=10)
        self.share_text.pack(fill=tk.X)
        self._theme_scrolled_text(self.share_text)

        btns = ttk.Frame(self.tab_share)
        btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btns, text="Export from JSON", command=self._share_export).pack(side=tk.LEFT)
        ttk.Button(btns, text="Import to JSON", command=self._share_import).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(
            self.tab_share,
            text=(
                "This is offline-only sharing: a compressed+encoded profile string. "
                "No network calls, no overlays/hooks, and nothing game-specific."
            ),
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

    def _build_overlay_tab(self) -> None:
        ttk.Label(
            self.tab_overlay,
            text=(
                "Safe overlay: this is just an always-on-top window. "
                "No process hooking, no injection, no memory reads."
            ),
            wraplength=900,
            justify="left",
        ).pack(anchor="w")

        btns = ttk.Frame(self.tab_overlay)
        btns.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btns, text="Open overlay", command=self._overlay_open).pack(side=tk.LEFT)
        ttk.Button(btns, text="Close overlay", command=self._overlay_close).pack(side=tk.LEFT, padx=(6, 0))

    def _build_controller_tab(self) -> None:
        # Connection background banner: left/right/both.
        self._bt_banner = tk.Frame(self.tab_controller, bg=self._colors["panel2"])
        self._bt_banner.pack(fill=tk.X, padx=8, pady=(8, 0))
        self._bt_banner_label = tk.Label(
            self._bt_banner,
            textvariable=self._bt_status,
            bg=self._colors["panel2"],
            fg=self._colors["text"],
            padx=10,
            pady=8,
            anchor="w",
        )
        self._bt_banner_label.pack(fill=tk.X)

        box = ttk.LabelFrame(self.tab_controller, text="Controller connection")
        box.pack(fill=tk.X, padx=8, pady=8)

        row1 = ttk.Frame(box)
        row1.pack(fill=tk.X, pady=(6, 0), padx=8)
        ttk.Label(row1, text="Preset:").pack(side=tk.LEFT)
        preset = ttk.Combobox(
            row1,
            textvariable=self._bt_target_preset,
            values=["Either (Joy-Con)", "Left (Joy-Con (L))", "Right (Joy-Con (R))", "Both (Joy-Con (L+R))", "Custom"],
            width=20,
            state="readonly",
        )
        preset.pack(side=tk.LEFT, padx=(8, 12))
        preset.bind("<<ComboboxSelected>>", lambda _e: self._bt_apply_preset())

        ttk.Label(row1, text="Target name contains:").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self._bt_target_substr, width=30).pack(side=tk.LEFT, padx=(8, 0))

        row2 = ttk.Frame(box)
        row2.pack(fill=tk.X, pady=(10, 6), padx=8)
        ttk.Button(row2, text="Connect / Scan", command=self._cmd_bt_connect, width=18).pack(side=tk.LEFT)
        # Status is shown in the banner above.

        note = (
            "This sends commands to the ESP32 BT host so you don't need to press buttons on the boards. "
            "Your controller may still need to be put into pairing mode (e.g. Joy-Con sync button)."
        )
        ttk.Label(self.tab_controller, text=note, wraplength=900, justify="left").pack(anchor="w", padx=12, pady=(4, 0))

        self._build_keymap_editor()

        self._update_bt_background()

    def _joycons_image_state(self) -> str:
        if self._bt_connected_left and self._bt_connected_right:
            return "both"
        if self._bt_connected_left:
            return "left"
        if self._bt_connected_right:
            return "right"
        return "none"

    def _find_joycons_png_variants(self) -> Dict[str, Path]:
        variant_names = {
            "none": "joycons-none.png",
            "left": "joycons-left.png",
            "right": "joycons-right.png",
            "both": "joycons-both.png",
        }
        search_roots = _joycons_search_roots()

        found: Dict[str, Path] = {}
        for state, file_name in variant_names.items():
            for root in search_roots:
                candidate = root / file_name
                try:
                    if candidate.exists():
                        found[state] = candidate
                        break
                except Exception:
                    continue

        fallback_base: Optional[Path] = None
        fallback_none: Optional[Path] = None
        fallback_candidates = [root / "joycons.png" for root in search_roots]
        none_candidates = [root / "joycons-grey.png" for root in search_roots]
        for candidate in fallback_candidates:
            try:
                if candidate.exists():
                    fallback_base = candidate
                    break
            except Exception:
                continue
        for candidate in none_candidates:
            try:
                if candidate.exists():
                    fallback_none = candidate
                    break
            except Exception:
                continue

        if fallback_base is not None:
            found.setdefault("both", fallback_base)
            found.setdefault("left", fallback_base)
            found.setdefault("right", fallback_base)
        if fallback_none is not None:
            found.setdefault("none", fallback_none)
        elif fallback_base is not None:
            found.setdefault("none", fallback_base)

        return found

    def _set_keymap_image_state(self, state: Optional[str] = None) -> None:
        next_state = state or self._joycons_image_state()
        if next_state not in JOYCONS_IMAGE_STATE_NAMES:
            next_state = "none"

        path = self._keymap_img_paths.get(next_state)
        if path == self._keymap_img_path and self._keymap_img_base is not None:
            self._keymap_img_state = next_state
            return

        self._keymap_img_state = next_state
        self._keymap_img_path = path
        self._keymap_img_base = None
        self._keymap_img_scaled = None

        if self._keymap_img_path:
            try:
                self._keymap_img_base = tk.PhotoImage(file=str(self._keymap_img_path))
            except Exception:
                self._keymap_img_base = None

    def _keymap_hotspots(self) -> Dict[str, int]:
        try:
            prof = self._current_profile()
        except Exception:
            return {}

        ui = prof.get("ui", {})
        if not isinstance(ui, dict):
            return {}
        hs = ui.get("hotspots", {})
        if not isinstance(hs, dict):
            return {}

        out: Dict[str, int] = {}
        for k, v in hs.items():
            if not isinstance(k, str) or not k:
                continue
            try:
                out[k] = int(v)
            except Exception:
                continue
        return out

    def _keymap_refresh_visuals(self) -> None:
        if not self._keymap_canvas:
            return
        self._keymap_redraw()

    def _mapping_load_from_profile(self, in_id: int) -> None:
        try:
            prof = self._current_profile()
        except Exception:
            return

        mappings = prof.get("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}

        entry = mappings.get(str(in_id))
        if not isinstance(entry, dict):
            self._mapping_type.set("passthrough")
            self._mapping_remap_to.set(str(in_id if in_id < 128 else (in_id - 128)))
            self._mapping_macro_id.set("")
            return

        et = entry.get("type")
        if et == "disable":
            self._mapping_type.set("disable")
        elif et == "remap":
            self._mapping_type.set("remap")
            to = entry.get("to")
            self._mapping_remap_to.set(str(int(to)) if isinstance(to, (int, float)) else "0")
        elif et == "macro":
            self._mapping_type.set("macro")
            mid = entry.get("id")
            self._mapping_macro_id.set(str(mid) if isinstance(mid, str) else "")
        else:
            self._mapping_type.set("passthrough")

    def _build_keymap_editor(self) -> None:
        box = ttk.LabelFrame(self.tab_controller, text="Keymap editor")
        box.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 8))

        top = ttk.Frame(box)
        top.pack(fill=tk.X, padx=8, pady=(6, 6))
        ttk.Label(top, textvariable=self._keymap_status, wraplength=720, justify="left").pack(side=tk.LEFT)

        btns = ttk.Frame(top)
        btns.pack(side=tk.RIGHT)
        ttk.Button(btns, text="Learn selected", command=self._keymap_begin_learn).pack(side=tk.LEFT)
        ttk.Button(btns, text="Clear binding", command=self._keymap_clear_selected).pack(side=tk.LEFT, padx=(6, 0))

        self._keymap_canvas = tk.Canvas(box, height=340, highlightthickness=1)
        self._keymap_canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        try:
            self._keymap_canvas.configure(bg=self._colors["panel2"], highlightbackground=self._colors["border"])
        except Exception:
            pass

        self._keymap_canvas.bind("<Button-1>", self._keymap_on_click)
        self._keymap_canvas.bind("<Configure>", lambda _e: self._keymap_redraw())

        self._keymap_img_paths = self._find_joycons_png_variants()
        self._set_keymap_image_state()

        self._keymap_redraw()

        # Minimal inline mapping controls for the selected/bound input key_id.
        map_box = ttk.LabelFrame(box, text="Selected input mapping")
        map_box.pack(fill=tk.X, padx=8, pady=(0, 8))
        r = ttk.Frame(map_box)
        r.pack(fill=tk.X, padx=8, pady=(6, 6))

        ttk.Label(r, text="Input key_id:").pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self._mapping_key_id, width=6).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r, text="Type:").pack(side=tk.LEFT)
        ttk.Combobox(
            r,
            textvariable=self._mapping_type,
            values=["passthrough", "disable", "remap", "macro"],
            width=14,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r, text="Remap to:").pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self._mapping_remap_to, width=6).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r, text="Macro id:").pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self._mapping_macro_id, width=14).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Button(r, text="Apply", command=self._mapping_apply).pack(side=tk.LEFT)

    def _keymap_redraw(self) -> None:
        c = self._keymap_canvas
        if not c:
            return

        c.delete("all")

        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)

        if not self._keymap_img_base:
            state_name = self._keymap_img_state
            msg = (
                f"Joy-Con image for state '{state_name}' not found"
                if not self._keymap_img_path
                else f"Failed to load Joy-Con image for state '{state_name}'"
            )
            c.create_text(w // 2, h // 2, text=msg, fill=self._colors.get("muted", "#666"))
            self._keymap_hotspot_px = {}
            return

        base_w = self._keymap_img_base.width()
        base_h = self._keymap_img_base.height()
        factor = max(1, int(math.ceil(base_w / max(1, w))), int(math.ceil(base_h / max(1, h))))

        try:
            self._keymap_img_scaled = self._keymap_img_base.subsample(factor, factor)
        except Exception:
            self._keymap_img_scaled = self._keymap_img_base

        img_w = self._keymap_img_scaled.width()
        img_h = self._keymap_img_scaled.height()
        ox = (w - img_w) / 2.0
        oy = (h - img_h) / 2.0

        c.create_image(ox, oy, image=self._keymap_img_scaled, anchor="nw")

        hs_bindings = self._keymap_hotspots()
        self._keymap_hotspot_px = {}
        radius = max(14, int(min(img_w, img_h) * 0.02))

        for name, nx, ny in KEYMAP_HOTSPOTS:
            px = ox + nx * img_w
            py = oy + ny * img_h
            self._keymap_hotspot_px[name] = (px, py)

            selected = (name == self._keymap_selected_name)
            bound = hs_bindings.get(name)

            outline = self._colors.get("accent", "#2b63ff") if selected else self._colors.get("border", "#333")
            fill = self._colors.get("panel", "#fff")
            text_col = self._colors.get("text", "#111")

            c.create_oval(px - radius, py - radius, px + radius, py + radius, outline=outline, width=2, fill=fill)
            label = name if bound is None else f"{name} {bound}"
            c.create_text(
                px,
                py,
                text=label,
                fill=text_col,
                font=(self._typo.get("font_family", "Segoe UI"), 9, "bold"),
            )

    def _keymap_pick_hotspot(self, x: float, y: float) -> Optional[str]:
        best: Optional[Tuple[str, float]] = None
        for name, (px, py) in self._keymap_hotspot_px.items():
            d2 = (px - x) ** 2 + (py - y) ** 2
            if best is None or d2 < best[1]:
                best = (name, d2)

        if not best:
            return None
        if best[1] > (40.0 * 40.0):
            return None
        return best[0]

    def _keymap_on_click(self, e: tk.Event) -> None:
        name = self._keymap_pick_hotspot(float(getattr(e, "x", 0)), float(getattr(e, "y", 0)))
        if not name:
            return

        self._keymap_selected_name = name
        hs = self._keymap_hotspots()
        bound = hs.get(name)
        if bound is None:
            self._mapping_key_id.set("")
            self._keymap_status.set(
                f"Selected: {name}. Not bound yet — click Learn selected, then press the controller button."
            )
        else:
            self._mapping_key_id.set(str(bound))
            self._mapping_load_from_profile(int(bound))
            self._keymap_status.set(f"Selected: {name} (key_id={bound}). Adjust mapping below, or Learn to re-bind.")

        self._keymap_redraw()

    def _keymap_begin_learn(self) -> None:
        if not self._keymap_selected_name:
            self._keymap_status.set("Select a control first.")
            return
        self._keymap_learn_name = self._keymap_selected_name
        self._keymap_status.set(f"Learning {self._keymap_selected_name}… press that controller button now.")

    def _keymap_bind_selected(self, key_id: int) -> None:
        if not self._keymap_learn_name:
            return
        try:
            prof = self._current_profile()
        except Exception:
            return

        ui = prof.setdefault("ui", {})
        if not isinstance(ui, dict):
            ui = {}
            prof["ui"] = ui
        hs = ui.setdefault("hotspots", {})
        if not isinstance(hs, dict):
            hs = {}
            ui["hotspots"] = hs

        hs[self._keymap_learn_name] = int(key_id)
        learned_name = self._keymap_learn_name
        self._keymap_learn_name = None
        self._keymap_selected_name = learned_name
        self._set_profile_obj(prof)

        self._mapping_key_id.set(str(int(key_id)))
        self._mapping_load_from_profile(int(key_id))
        self._keymap_status.set(f"Bound {learned_name} → key_id={int(key_id)}")

    def _keymap_clear_selected(self) -> None:
        if not self._keymap_selected_name:
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        ui = prof.get("ui", {})
        if not isinstance(ui, dict):
            return
        hs = ui.get("hotspots", {})
        if not isinstance(hs, dict):
            return

        hs.pop(self._keymap_selected_name, None)
        self._set_profile_obj(prof)
        self._mapping_key_id.set("")
        self._keymap_status.set(f"Cleared binding for {self._keymap_selected_name}.")

    def _update_bt_background(self) -> None:
        if not self._bt_banner or not self._bt_banner_label:
            return

        # Theme-matched colors (see tools/generate_ui_bundle.py for the theme.json tokens)
        neutral_bg = self._colors["panel2"]
        neutral_fg = _contrast_on(neutral_bg)
        left_bg = self._colors["accent"]
        right_bg = self._colors["accent2"]
        both_bg = _blend_hex(left_bg, right_bg, 0.5)

        if self._bt_connected_left and self._bt_connected_right:
            bg = both_bg
        elif self._bt_connected_left:
            bg = left_bg
        elif self._bt_connected_right:
            bg = right_bg
        else:
            bg = neutral_bg

        self._bt_banner.configure(bg=bg)
        self._bt_banner_label.configure(bg=bg, fg=_contrast_on(bg))
        self._set_keymap_image_state()
        self._keymap_refresh_visuals()

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

        try:
            self.port_combo["values"] = ports
        except Exception:
            pass

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
        self._keymap_refresh_visuals()

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

            # Keymap editor learn mode: bind hotspot -> observed input key_id.
            if pressed and self._keymap_learn_name:
                self._keymap_bind_selected(key_id)

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
        self._overlay = OverlayWindow(self, theme=self._ui_theme)
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

        axis = self._colors.get("border", "#22314f")
        curve_col = self._colors.get("accent", "#2b63ff")

        # axes
        c.create_line(pad, h - pad, w - pad, h - pad, fill=axis)
        c.create_line(pad, h - pad, pad, pad, fill=axis)

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
            c.create_line(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1], fill=curve_col)

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
