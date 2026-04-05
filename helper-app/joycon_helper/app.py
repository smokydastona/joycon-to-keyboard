from __future__ import annotations

import base64
import copy
import json
import logging
import math
import sys
import threading
import tkinter as tk
import tkinter.ttk as ttk
import time
import zlib
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText
from typing import Any, Dict, List, Optional, Tuple

try:
    import winsound  # Windows only
    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False

try:
    from PIL import Image as PILImage, ImageTk  # type: ignore
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

from serial.tools import list_ports

from .serial_client import SerialClient
from ._version import __version__
from . import updater
from . import fw_updater
from . import hid_keycodes
from . import m913_device

log = logging.getLogger("joycon_helper.app")


DEFAULT_UI_THEME: dict = {
    "name": "sketchbook-ink",
    "version": 2,
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
        "active": "#2b6a4b",
        "conflict": "#b42318",
        "modified": "#a16207",
        "selected": "#2f4a9e",
        "pulse_bright": "#60c090",
        "timeline_press": "#2b6a4b",
        "timeline_release": "#6b5d48",
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


DARK_UI_THEME: dict = {
    "name": "sketchbook-ink-dark",
    "version": 2,
    "colors": {
        "bg": "#10141c",
        "panel": "#181e2c",
        "panel2": "#202838",
        "text": "#a8bcd0",
        "muted": "#6888aa",
        "border": "#2a3a54",
        "accent": "#4a7cc8",
        "accent2": "#3a8a5c",
        "danger": "#c84848",
        "warning": "#b89030",
        "active": "#3a8a5c",
        "conflict": "#c84848",
        "modified": "#b89030",
        "selected": "#4a7cc8",
        "pulse_bright": "#60c898",
        "timeline_press": "#3a8a5c",
        "timeline_release": "#6888aa",
    },
    "typography": {
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
        log.debug("Failed to resolve _MEIPASS", exc_info=True)
        return None


def _executable_dir() -> Optional[Path]:
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve().parent
    except Exception:
        log.debug("Failed to resolve executable dir", exc_info=True)
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
        return {"ver": 1, "name": "default", "mappings": {}, "macros": [], "layers": [], "chords": [], "stick": {}, "ui": {"hotspots": {}}}

    profile.setdefault("ver", 1)
    profile.setdefault("name", "default")
    profile.setdefault("mappings", {})
    profile.setdefault("macros", [])
    profile.setdefault("layers", [])
    profile.setdefault("chords", [])
    profile.setdefault("stick", {})
    profile.setdefault("ui", {"hotspots": {}})

    if not isinstance(profile["mappings"], dict):
        profile["mappings"] = {}
    if not isinstance(profile["macros"], list):
        profile["macros"] = []
    if not isinstance(profile.get("layers"), list):
        profile["layers"] = []
    if not isinstance(profile.get("chords"), list):
        profile["chords"] = []
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

M913_IMAGE_STATE_NAMES = ("none", "connected")

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
        self.title("Bind Bandit Overlay")
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
            text="Bind Bandit Overlay",
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
        self.title("Bind Bandit")
        self.geometry("980x720")

        # Window icon — look next to the exe (frozen), otherwise next to this file.
        _icon_path = self._find_icon()
        if _icon_path:
            try:
                self.iconbitmap(str(_icon_path))
            except tk.TclError:
                log.debug("iconbitmap failed for %s", _icon_path)

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

        # M913 mouse overlay image (Mouse tab)
        self._m913_overlay_canvas: Optional[tk.Canvas] = None
        self._m913_img_state: str = "none"
        self._m913_img_paths: Dict[str, Path] = {}
        self._m913_img_path: Optional[Path] = None
        self._m913_img_base: Optional[tk.PhotoImage] = None
        self._m913_img_scaled: Optional[tk.PhotoImage] = None

        # Press-to-bind state
        self._bind_mode = False  # True = waiting for a keyboard key press
        self._bind_hotspot: Optional[str] = None  # hotspot name being bound

        # Live input state: set of currently-pressed key_ids
        self._active_key_ids: set[int] = set()

        # Layer editor state
        self._layer_edit_index = tk.IntVar(value=-1)  # -1 = base layer

        # Pulse animation state for active hotspot highlighting
        self._pulse_phase: float = 0.0
        self._pulse_growing: bool = True

        # Chord definitions (profile-level, list of {"keys": [int,...], "action": {...}})
        self._chord_entries: List[Dict[str, Any]] = []

        # Event timeline entries for Input Test tab: list of (timestamp, text, color)
        self._event_timeline: List[Tuple[float, str, str]] = []
        self._timeline_canvas: Optional[tk.Canvas] = None

        # Pre-initialize Input Test tab variables (used before tab is built)
        self._input_test_active_var = tk.StringVar(value="(none)")

        # ── Undo / Redo history ──
        self._undo_stack: List[Tuple[str, str]] = []  # (description, json_snapshot)
        self._redo_stack: List[Tuple[str, str]] = []
        self._undo_max = 50
        self._suppress_undo = False  # True during undo/redo to prevent re-push

        # ── Adaptive UI mode (simple / advanced) ──
        self._ui_mode = tk.StringVar(value="advanced")
        self._advanced_widgets: List[tk.Widget] = []  # widgets hidden in simple mode

        # ── Sandbox mode ──
        self._sandbox_active = tk.BooleanVar(value=False)
        self._sandbox_snapshot: Optional[str] = None

        # ── Smart search ──
        self._search_var = tk.StringVar(value="")
        self._search_matches: List[str] = []  # hotspot names matching current search

        # ── Guided wizard state ──
        self._guided_window: Optional[tk.Toplevel] = None

        # ── Lock critical inputs ──
        self._locked_hotspots: set[str] = set()  # hotspot names that require confirmation to unbind

        # ── Drag-and-drop state ──
        self._drag_source: Optional[str] = None  # keysym being dragged
        self._drag_item: Optional[int] = None  # canvas item id for drag ghost

        # ── Performance: dirty-flag batched keymap redraw ──
        self._keymap_dirty: bool = False  # True = needs redraw on next pulse tick
        self._keymap_canvas_items: Dict[str, list] = {}  # hotspot name → [canvas item ids]
        self._keymap_bg_item: Optional[int] = None  # canvas item id for background image
        self._keymap_last_scale_factor: int = 0  # cached subsample factor
        self._keymap_last_canvas_size: Tuple[int, int] = (0, 0)  # (w, h)

        # ── Performance: cached conflict detection ──
        self._conflict_cache: Optional[Dict[str, List[str]]] = None  # invalidated on profile change
        self._conflict_hotspot_cache: Optional[set] = None

        # ── Performance: cached reverse lookup ──
        self._key_id_to_hotspot_cache: Optional[Dict[int, str]] = None

        # ── Performance: timeline change tracking ──
        self._timeline_last_count: int = 0  # event count at last draw
        self._timeline_last_draw_time: float = 0.0

        # ── Performance: lazy tab loading ──
        self._tabs_built: set[str] = set()  # tab names that have been built

        # ── Performance: latency profiling ──
        self._perf_enabled: bool = False
        self._perf_redraw_times: List[float] = []  # last N redraw durations
        self._perf_input_times: List[Tuple[float, float]] = []  # (recv_time, process_time)

        self._build_ui()
        self._load_background_image()
        self._apply_widget_theme()
        self._refresh_ports()
        self.after(50, self._drain_rx)
        self.after(80, self._pulse_tick)

        # Bind undo/redo keyboard shortcuts
        self.bind("<Control-z>", lambda _e: self._undo())
        self.bind("<Control-y>", lambda _e: self._redo())
        self.bind("<Control-Z>", lambda _e: self._undo())
        self.bind("<Control-Y>", lambda _e: self._redo())

        # Check for updates in the background after the UI is visible.
        self._pending_update: Optional[Dict[str, Any]] = None
        self.after(2000, self._start_update_check)

        # Check for firmware left from a previous app update.
        self._pending_fw_files = updater.load_pending_firmware()
        self._pending_fw_offered = False
        if self._pending_fw_files:
            self.after(3000, self._check_pending_fw)

    @staticmethod
    def _find_icon() -> Optional[Path]:
        """Locate icon.ico next to the exe (frozen) or in the helper-app dir."""
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / "icon.ico")
        candidates.append(Path(__file__).resolve().parent.parent / "icon.ico")
        for p in candidates:
            if p.is_file():
                return p
        return None

    def _find_background_png(self) -> Optional[Path]:
        """Locate the appropriate background PNG (light or dark) for the app."""
        prefer_dark = self._detect_dark_preference()
        name = "background-dark.png" if prefer_dark else "background.png"

        search_roots = list(_joycons_search_roots())
        # Also check docs/ui/ directly (where the PNGs live in the repo).
        here = Path(__file__).resolve()
        search_roots.append(here.parents[3] / "docs" / "ui")
        try:
            search_roots.append(Path.cwd() / "docs" / "ui")
        except Exception:
            pass

        for root in _dedupe_paths(search_roots):
            candidate = root / name
            try:
                if candidate.is_file():
                    return candidate
            except Exception:
                continue
        return None

    def _load_background_image(self) -> None:
        """Load the background PNG and place it behind all other widgets."""
        if not _HAS_PIL:
            return

        bg_path = self._find_background_png()
        if not bg_path:
            return

        try:
            self._bg_pil_original = PILImage.open(bg_path).convert("RGBA")
        except Exception:
            log.debug("Failed to load background image %s", bg_path, exc_info=True)
            return

        self._bg_label = tk.Label(self, bd=0, highlightthickness=0)
        self._bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        self._bg_label.lower()  # Ensure it stays behind all other widgets.

        self.bind("<Configure>", self._on_resize_bg)
        # Trigger initial draw after the window has been mapped.
        self.after(50, self._refresh_bg)

    def _refresh_bg(self) -> None:
        """Scale the background image to fit the current window size."""
        if not hasattr(self, "_bg_pil_original") or self._bg_pil_original is None:
            return

        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2:
            return

        # Avoid redundant resizes.
        if hasattr(self, "_bg_last_size") and self._bg_last_size == (w, h):
            return
        self._bg_last_size = (w, h)

        # Scale to cover the window (crop edges if aspect ratio differs).
        orig_w, orig_h = self._bg_pil_original.size
        scale = max(w / orig_w, h / orig_h)
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)

        resized = self._bg_pil_original.resize((new_w, new_h), PILImage.LANCZOS)

        # Center-crop to window size.
        left = (new_w - w) // 2
        top = (new_h - h) // 2
        cropped = resized.crop((left, top, left + w, top + h))

        self._bg_photo = ImageTk.PhotoImage(cropped)
        self._bg_label.configure(image=self._bg_photo)

    def _on_resize_bg(self, event: tk.Event) -> None:
        """Handle window resize to update background image."""
        if event.widget is not self:
            return
        self._refresh_bg()

    def _load_ui_theme(self) -> dict:
        # Decide light vs dark: check --dark flag, env var, or Windows dark-mode setting.
        prefer_dark = self._detect_dark_preference()

        if prefer_dark:
            # Try dark bundle first.
            dark_candidates = [root.parent / (root.name + "-dark") / "theme.json"
                               for root in _ui_bundle_search_roots()]
            for c in dark_candidates:
                try:
                    if c.exists():
                        log.info("Loading dark theme from %s", c)
                        return _load_theme_json(c)
                except Exception:
                    log.debug("Failed to load dark theme from %s", c, exc_info=True)
                    continue
            log.info("Using built-in dark theme")
            return DARK_UI_THEME

        # Light: load from bundle or fallback.
        candidates = [root / "theme.json" for root in _ui_bundle_search_roots()]

        for c in candidates:
            try:
                if c.exists():
                    log.info("Loading light theme from %s", c)
                    return _load_theme_json(c)
            except Exception:
                log.debug("Failed to load theme from %s", c, exc_info=True)
                continue

        log.info("Using built-in light theme")
        return DEFAULT_UI_THEME

    @staticmethod
    def _detect_dark_preference() -> bool:
        """Return True if the user/system prefers dark mode."""
        import os
        # Explicit env var override: JOYCON_THEME=dark
        env = os.environ.get("JOYCON_THEME", "").strip().lower()
        if env == "dark":
            return True
        if env == "light":
            return False
        # CLI flag passed via sys.argv
        if "--dark" in sys.argv:
            return True
        # Windows 10+ dark-mode registry check
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return val == 0
        except Exception:
            pass
        return False

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

        # Update icon — hidden until an update is detected.
        self._update_icon_btn = ttk.Button(
            top, text=" \u2191 Update available ",
            command=self._open_update_dialog,
        )
        # Not packed yet — _on_update_result shows it when an update exists.

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
        self.tab_input_test = ttk.Frame(self.tabs)
        self.tab_mouse = ttk.Frame(self.tabs)
        self.tab_help = ttk.Frame(self.tabs)

        self.tabs.add(self.tab_profile, text="Profile")
        self.tabs.add(self.tab_macros, text="Macros")
        self.tabs.add(self.tab_stick, text="Stick")
        self.tabs.add(self.tab_share, text="Share")
        self.tabs.add(self.tab_overlay, text="Overlay")
        self.tabs.add(self.tab_controller, text="Controller")
        self.tabs.add(self.tab_input_test, text="Input Test")
        self.tabs.add(self.tab_mouse, text="Mouse")
        self.tabs.add(self.tab_help, text="Help")

        # Build critical tabs eagerly; defer the rest until first selected.
        self._build_profile_tab()
        self._build_controller_tab()

        # Lazy-load remaining tabs on first selection.
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)

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
        ttk.Button(right, text="Safe mode (reset slot)", command=self._cmd_safe_mode, width=22).pack(pady=(6, 0))

        ttk.Label(right, text="Raw command (JSON line)").pack(anchor="w", pady=(14, 0))
        self.raw_entry = ttk.Entry(right, width=30)
        self.raw_entry.pack(pady=(4, 0))
        ttk.Button(right, text="Send", command=self._send_raw, width=22).pack(pady=(6, 0))

        # Version label (bottom of right panel)
        ver_frame = ttk.Frame(right)
        ver_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        ttk.Label(ver_frame, text=f"v{__version__}", style="Muted.TLabel").pack(anchor="w")

        # Firmware update section
        fw_frame = ttk.LabelFrame(ver_frame, text="Firmware")
        fw_frame.pack(fill=tk.X, pady=(8, 0))
        self._fw_s3_ver = tk.StringVar(value="S3: —")
        self._fw_esp32_ver = tk.StringVar(value="ESP32: —")
        ttk.Label(fw_frame, textvariable=self._fw_s3_ver, style="Muted.TLabel").pack(anchor="w", padx=4)
        ttk.Label(fw_frame, textvariable=self._fw_esp32_ver, style="Muted.TLabel").pack(anchor="w", padx=4)
        self._fw_status = tk.StringVar(value="")
        ttk.Label(fw_frame, textvariable=self._fw_status, style="Muted.TLabel", wraplength=170).pack(anchor="w", padx=4, pady=(2, 0))
        self._fw_check_btn = ttk.Button(fw_frame, text="Check firmware versions", command=self._fw_check_versions, width=22)
        self._fw_check_btn.pack(pady=(4, 4))
        self._fw_update_btn = ttk.Button(fw_frame, text="Update firmware", command=self._fw_do_update, width=22, state="disabled")
        self._fw_update_btn.pack(pady=(0, 4))
        self._pending_fw_update: Optional[Dict[str, Any]] = None

        # ── Bottom status bar (mode indicator — always visible) ──
        status_bar = tk.Frame(self, bg=self._colors.get("panel2", "#e2d0a8"), relief="sunken", bd=1)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self._mode_indicator_var = tk.StringVar(value="")
        tk.Label(
            status_bar,
            textvariable=self._mode_indicator_var,
            bg=self._colors.get("panel2", "#e2d0a8"),
            fg=self._colors.get("text", "#2a1f0e"),
            font=(self._typo.get("font_family", "Segoe UI"), 8),
            anchor="w",
            padx=8,
            pady=2,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Undo/redo buttons in status bar
        self._redo_btn = ttk.Button(status_bar, text="Redo", command=self._redo, width=5, state="disabled")
        self._redo_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=1)
        self._undo_btn = ttk.Button(status_bar, text="Undo", command=self._undo, width=5, state="disabled")
        self._undo_btn.pack(side=tk.RIGHT, padx=(4, 0), pady=1)

        # UI mode toggle in status bar
        self._ui_mode_btn = ttk.Button(
            status_bar, text="Simple mode",
            command=self._toggle_ui_mode, width=12,
        )
        self._ui_mode_btn.pack(side=tk.RIGHT, padx=(4, 8), pady=1)

        self._undo_history_var = tk.StringVar(value="History: (empty)")

        # Start periodic mode indicator refresh
        self.after(300, self._mode_indicator_tick)

    def _on_tab_changed(self, _event: Any = None) -> None:
        """Lazy-build tab contents on first selection."""
        try:
            tab_id = self.tabs.select()
            tab_name = self.tabs.tab(tab_id, "text")
        except Exception:
            return
        self._ensure_tab_built(tab_name)

    def _ensure_tab_built(self, tab_name: str) -> None:
        """Build a tab's contents if not already built."""
        if tab_name in self._tabs_built:
            return
        self._tabs_built.add(tab_name)
        builders: Dict[str, Any] = {
            "Macros": self._build_macros_tab,
            "Stick": self._build_stick_tab,
            "Share": self._build_share_tab,
            "Overlay": self._build_overlay_tab,
            "Input Test": self._build_input_test_tab,
            "Mouse": self._build_mouse_tab,
            "Help": self._build_help_tab,
        }
        builder = builders.get(tab_name)
        if builder:
            builder()
            self._apply_widget_theme()

    def _build_profile_tab(self) -> None:
        # ── Slot quick-select row ──
        slot_frame = ttk.LabelFrame(self.tab_profile, text="Profile slots")
        slot_frame.pack(fill=tk.X, pady=(0, 4))
        slot_row = ttk.Frame(slot_frame)
        slot_row.pack(fill=tk.X, padx=8, pady=(4, 4))
        self._slot_buttons: List[ttk.Button] = []
        self._slot_name_vars: List[tk.StringVar] = []
        for i in range(4):
            sv = tk.StringVar(value=f"Slot {i}")
            self._slot_name_vars.append(sv)
            btn = ttk.Button(
                slot_row,
                textvariable=sv,
                command=lambda idx=i: self._slot_select(idx),
                width=16,
            )
            btn.pack(side=tk.LEFT, padx=(0, 6))
            self._slot_buttons.append(btn)
        ttk.Button(slot_row, text="Read all names", command=self._slot_read_all).pack(side=tk.LEFT, padx=(12, 0))

        # Profile management row
        mgmt = ttk.Frame(self.tab_profile)
        mgmt.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(mgmt, text="Name:").pack(side=tk.LEFT)
        self._profile_name_var = tk.StringVar(value="default")
        self._profile_name_entry = ttk.Entry(mgmt, textvariable=self._profile_name_var, width=20)
        self._profile_name_entry.pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(mgmt, text="Rename", command=self._profile_rename).pack(side=tk.LEFT)
        ttk.Button(mgmt, text="Duplicate", command=self._profile_duplicate).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(mgmt, text="Reset to defaults", command=self._profile_reset_defaults).pack(side=tk.LEFT, padx=(6, 0))

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

        # ── Built-in community presets ──
        preset_box = ttk.LabelFrame(self.tab_share, text="Quick-start presets")
        preset_box.pack(fill=tk.X, padx=0, pady=(12, 0))
        ttk.Label(
            preset_box,
            text="Load a ready-made mapping preset. This replaces the current profile mappings.",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(4, 2))
        preset_row = ttk.Frame(preset_box)
        preset_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        for pname, pdesc in [
            ("FPS / Shooter", "WASD + Space jump, Shift sprint, R reload, E interact, mouse-like aiming"),
            ("Platformer", "Left/Right on D-pad, A jump, B attack, triggers for special"),
            ("RPG / Action", "WASD move, 1-4 hotbar, E interact, I inventory, Space roll"),
        ]:
            ttk.Button(preset_row, text=pname, command=lambda n=pname: self._apply_community_preset(n)).pack(
                side=tk.LEFT, padx=(0, 6)
            )

    def _apply_community_preset(self, name: str) -> None:
        """Apply a built-in community preset mapping set."""
        # Each preset defines (hotspot_name → hid_keycode) mappings.
        presets: Dict[str, Dict[str, Tuple[int, int]]] = {
            "FPS / Shooter": {
                "DUp": (0, 0x1A),     # W
                "DDown": (0, 0x16),   # S
                "DLeft": (0, 0x04),   # A
                "DRight": (0, 0x07),  # D
                "A": (0, 0x2C),       # Space (jump)
                "B": (0, 0x06),       # C (crouch)
                "X": (0, 0x15),       # R (reload)
                "Y": (0, 0x08),       # E (interact)
                "L": (0, 0xE1),       # Shift (sprint)
                "R": (0, 0xE0),       # Ctrl (aim)
                "ZL": (0, 0x1D),      # Z
                "ZR": (0, 0x09),      # F
            },
            "Platformer": {
                "DLeft": (0, 0x50),   # Left arrow
                "DRight": (0, 0x4F),  # Right arrow
                "DUp": (0, 0x52),     # Up arrow
                "DDown": (0, 0x51),   # Down arrow
                "A": (0, 0x2C),       # Space (jump)
                "B": (0, 0x1B),       # X (attack)
                "X": (0, 0x1D),       # Z (special)
                "Y": (0, 0x06),       # C (grab)
                "L": (0, 0xE1),       # Shift (run)
                "R": (0, 0xE0),       # Ctrl
            },
            "RPG / Action": {
                "DUp": (0, 0x1A),     # W
                "DDown": (0, 0x16),   # S
                "DLeft": (0, 0x04),   # A
                "DRight": (0, 0x07),  # D
                "A": (0, 0x2C),       # Space (roll/dodge)
                "B": (0, 0x08),       # E (interact)
                "X": (0, 0x0C),       # I (inventory)
                "Y": (0, 0x1E),       # 1 (hotbar)
                "L": (0, 0xE1),       # Shift (sprint)
                "R": (0, 0xE0),       # Ctrl (block)
                "ZL": (0, 0x1F),      # 2 (hotbar)
                "ZR": (0, 0x20),      # 3 (hotbar)
            },
        }
        preset = presets.get(name)
        if not preset:
            return
        if not messagebox.askyesno("Apply preset", f"Replace current mappings with '{name}' preset?"):
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        hs = prof.setdefault("ui", {}).setdefault("hotspots", {})
        mappings = prof.setdefault("mappings", {})
        for hotspot, (mod, kc) in preset.items():
            kid = hs.get(hotspot)
            if kid is None:
                continue
            mappings[str(kid)] = {"type": "remap_hid", "mod": mod, "keycode": kc}
        self._set_profile_obj(prof, undo_label=f"preset:{name}")
        self._keymap_redraw()
        self._rebuild_layer_stack()
        self._play_sound("bind")
        self._log_line(f"[host] Applied community preset: {name}")

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

    # ------------------------------------------------------------------
    # M913 mouse overlay image helpers
    # ------------------------------------------------------------------

    def _find_m913_png_variants(self) -> Dict[str, Path]:
        variant_names = {
            "connected": "m913.png",
            "none": "m913-none.png",
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

        # Fallback: use connected image for disconnected state if only one exists
        if "connected" in found and "none" not in found:
            found["none"] = found["connected"]
        elif "none" in found and "connected" not in found:
            found["connected"] = found["none"]

        return found

    def _m913_set_image_state(self, state: str = "none") -> None:
        if state not in M913_IMAGE_STATE_NAMES:
            state = "none"

        path = self._m913_img_paths.get(state)
        if path == self._m913_img_path and self._m913_img_base is not None:
            self._m913_img_state = state
            return

        self._m913_img_state = state
        self._m913_img_path = path
        self._m913_img_base = None
        self._m913_img_scaled = None

        if self._m913_img_path:
            try:
                self._m913_img_base = tk.PhotoImage(file=str(self._m913_img_path))
            except Exception:
                self._m913_img_base = None

        self._m913_redraw_overlay()

    def _m913_redraw_overlay(self) -> None:
        c = self._m913_overlay_canvas
        if not c:
            return

        c.delete("all")

        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)

        if not self._m913_img_base:
            msg = "M913 mouse image not found" if not self._m913_img_path else "Failed to load M913 image"
            c.create_text(w // 2, h // 2, text=msg, fill=self._colors.get("muted", "#666"))
            return

        base_w = self._m913_img_base.width()
        base_h = self._m913_img_base.height()
        factor = max(1, int(math.ceil(base_w / max(1, w))), int(math.ceil(base_h / max(1, h))))

        try:
            self._m913_img_scaled = self._m913_img_base.subsample(factor, factor)
        except Exception:
            self._m913_img_scaled = self._m913_img_base

        img_w = self._m913_img_scaled.width()
        img_h = self._m913_img_scaled.height()
        ox = (w - img_w) / 2.0
        oy = (h - img_h) / 2.0
        c.create_image(ox, oy, image=self._m913_img_scaled, anchor="nw")

    # ------------------------------------------------------------------
    # Pulse animation for active hotspot highlighting
    # ------------------------------------------------------------------

    def _pulse_tick(self) -> None:
        """Advance the pulse animation phase and redraw if active keys exist or dirty."""
        if self._active_key_ids:
            step = 0.07
            if self._pulse_growing:
                self._pulse_phase += step
                if self._pulse_phase >= 1.0:
                    self._pulse_phase = 1.0
                    self._pulse_growing = False
            else:
                self._pulse_phase -= step
                if self._pulse_phase <= 0.3:
                    self._pulse_phase = 0.3
                    self._pulse_growing = True
            self._keymap_redraw()
        elif self._keymap_dirty:
            self._keymap_redraw()
        else:
            self._pulse_phase = 0.0
            self._pulse_growing = True
        self.after(80, self._pulse_tick)

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
        self._invalidate_caches()
        # Force full rebuild by clearing canvas items cache
        self._keymap_canvas_items = {}
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
        elif et == "remap_hid":
            self._mapping_type.set("remap_hid")
            mod = entry.get("mod", 0)
            kc = entry.get("keycode", 0)
            self._mapping_remap_to.set(f"0x{kc:02X}" if isinstance(kc, int) else "0")
        elif et == "macro":
            self._mapping_type.set("macro")
            mid = entry.get("id")
            self._mapping_macro_id.set(str(mid) if isinstance(mid, str) else "")
        elif et == "tap_hold":
            self._mapping_type.set("tap_hold")
            hold = entry.get("hold", {})
            if isinstance(hold, dict):
                kc = hold.get("keycode", 0)
                self._mapping_remap_to.set(f"0x{kc:02X}" if isinstance(kc, int) else "0")
        else:
            self._mapping_type.set("passthrough")

    def _build_keymap_editor(self) -> None:
        box = ttk.LabelFrame(self.tab_controller, text="Keymap editor")
        box.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 8))

        top = ttk.Frame(box)
        top.pack(fill=tk.X, padx=8, pady=(6, 6))
        ttk.Label(top, textvariable=self._keymap_status, wraplength=480, justify="left").pack(side=tk.LEFT)

        btns = ttk.Frame(top)
        btns.pack(side=tk.RIGHT)
        ttk.Button(btns, text="Guided Setup", command=self._open_guided_wizard).pack(side=tk.LEFT)
        ttk.Button(btns, text="Smart Defaults", command=self._apply_smart_defaults).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Learn selected", command=self._keymap_begin_learn).pack(side=tk.LEFT, padx=(6, 0))
        self._bind_btn = ttk.Button(btns, text="Bind key", command=self._keymap_begin_bind)
        self._bind_btn.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Clear binding", command=self._keymap_clear_selected).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btns, text="Reset button", command=self._keymap_reset_selected).pack(side=tk.LEFT, padx=(6, 0))

        # ── Search bar ──
        search_row = ttk.Frame(box)
        search_row.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Label(search_row, text="Search:").pack(side=tk.LEFT)
        search_entry = ttk.Entry(search_row, textvariable=self._search_var, width=20)
        search_entry.pack(side=tk.LEFT, padx=(4, 8))
        self._search_var.trace_add("write", self._on_search_changed)
        ttk.Button(search_row, text="Clear", command=lambda: self._search_var.set("")).pack(side=tk.LEFT)

        # Sandbox toggle
        ttk.Checkbutton(
            search_row, text="Sandbox mode", variable=self._sandbox_active,
            command=self._toggle_sandbox,
        ).pack(side=tk.RIGHT, padx=(12, 0))

        self._keymap_canvas = tk.Canvas(box, height=340, highlightthickness=1)
        self._keymap_canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        try:
            self._keymap_canvas.configure(bg=self._colors["panel2"], highlightbackground=self._colors["border"])
        except Exception:
            pass

        self._keymap_canvas.bind("<Button-1>", self._keymap_on_click)
        self._keymap_canvas.bind("<Button-3>", self._keymap_on_right_click)
        self._keymap_canvas.bind("<Configure>", lambda _e: self._keymap_redraw())
        self._keymap_canvas.bind("<Motion>", self._keymap_on_motion)

        # Bind keyboard events for press-to-bind.
        self.bind("<KeyPress>", self._on_keypress_bind)

        self._keymap_img_paths = self._find_joycons_png_variants()
        self._set_keymap_image_state()

        self._keymap_redraw()

        # Layer selector
        layer_box = ttk.LabelFrame(box, text="Layer")
        layer_box.pack(fill=tk.X, padx=8, pady=(0, 4))
        layer_row = ttk.Frame(layer_box)
        layer_row.pack(fill=tk.X, padx=8, pady=(4, 4))
        ttk.Radiobutton(layer_row, text="Base", variable=self._layer_edit_index, value=-1,
                        command=self._keymap_redraw).pack(side=tk.LEFT)
        for li in range(4):
            ttk.Radiobutton(layer_row, text=f"Layer {li+1}", variable=self._layer_edit_index, value=li,
                            command=self._keymap_redraw).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(layer_row, text="Add layer", command=self._layer_add).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Button(layer_row, text="Remove layer", command=self._layer_remove).pack(side=tk.LEFT, padx=(6, 0))

        # Layer activation config (only visible when a layer is selected)
        self._layer_cfg_frame = ttk.Frame(layer_box)
        self._layer_cfg_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._advanced_widgets.append(self._layer_cfg_frame)
        ttk.Label(self._layer_cfg_frame, text="Activation key_id:").pack(side=tk.LEFT)
        self._layer_key_id_var = tk.StringVar(value="")
        ttk.Entry(self._layer_cfg_frame, textvariable=self._layer_key_id_var, width=6).pack(side=tk.LEFT, padx=(4, 8))
        self._layer_mode_var = tk.StringVar(value="hold")
        ttk.Label(self._layer_cfg_frame, text="Mode:").pack(side=tk.LEFT)
        ttk.Combobox(self._layer_cfg_frame, textvariable=self._layer_mode_var,
                     values=["hold", "toggle"], width=8, state="readonly").pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(self._layer_cfg_frame, text="Name:").pack(side=tk.LEFT)
        self._layer_name_var = tk.StringVar(value="")
        ttk.Entry(self._layer_cfg_frame, textvariable=self._layer_name_var, width=14).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(self._layer_cfg_frame, text="Apply layer config", command=self._layer_apply_config).pack(side=tk.LEFT)

        # Visual layer stack summary
        self._layer_stack_frame = ttk.Frame(layer_box)
        self._layer_stack_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._layer_stack_labels: list[ttk.Label] = []
        self._advanced_widgets.append(self._layer_stack_frame)
        self._rebuild_layer_stack()

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
            values=["passthrough", "disable", "remap", "remap_hid", "macro", "tap_hold"],
            width=14,
            state="readonly",
        ).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r, text="Remap to:").pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self._mapping_remap_to, width=6).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(r, text="Macro id:").pack(side=tk.LEFT)
        ttk.Entry(r, textvariable=self._mapping_macro_id, width=14).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Button(r, text="Apply", command=self._mapping_apply).pack(side=tk.LEFT)

        # Conflict warning label
        self._conflict_var = tk.StringVar(value="")
        self._conflict_label = ttk.Label(box, textvariable=self._conflict_var, foreground=self._colors.get("danger", "red"))
        self._conflict_label.pack(fill=tk.X, padx=8, pady=(0, 4))

        # Fix-conflicts button (hidden when no conflicts)
        self._conflict_fix_btn = ttk.Button(box, text="Auto-fix conflicts", command=self._conflict_auto_fix)
        self._conflict_fix_btn.pack(padx=8, anchor="w", pady=(0, 4))
        self._conflict_fix_btn.pack_forget()  # hidden by default

        # ── Chording section ──
        chord_box = ttk.LabelFrame(box, text="Chords (multi-button combos)")
        chord_box.pack(fill=tk.X, padx=8, pady=(0, 8))
        self._advanced_widgets.append(chord_box)
        chord_info = ttk.Label(
            chord_box,
            text="Define combos: press multiple controller buttons simultaneously for a different action.",
            wraplength=700,
            justify="left",
        )
        chord_info.pack(anchor="w", padx=8, pady=(4, 2))
        chord_row = ttk.Frame(chord_box)
        chord_row.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Label(chord_row, text="Keys (comma-sep key_ids):").pack(side=tk.LEFT)
        self._chord_keys_var = tk.StringVar(value="")
        ttk.Entry(chord_row, textvariable=self._chord_keys_var, width=16).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(chord_row, text="Output keycode:").pack(side=tk.LEFT)
        self._chord_output_var = tk.StringVar(value="")
        ttk.Entry(chord_row, textvariable=self._chord_output_var, width=8).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(chord_row, text="Add chord", command=self._chord_add).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(chord_row, text="Clear chords", command=self._chord_clear).pack(side=tk.LEFT, padx=(4, 0))

        self._chord_list_var = tk.StringVar(value="(none)")
        ttk.Label(chord_box, textvariable=self._chord_list_var, wraplength=700, justify="left").pack(
            anchor="w", padx=8, pady=(0, 4)
        )

    def _get_mapping_output(self, key_id: int) -> Optional[Tuple[int, int]]:
        """Return the (mod, keycode) output for a key_id, or None if passthrough/default."""
        try:
            prof = self._current_profile()
        except Exception:
            return None
        mappings = prof.get("mappings", {})
        if not isinstance(mappings, dict):
            return None
        entry = mappings.get(str(key_id))
        if not isinstance(entry, dict):
            # Passthrough — use default keymap
            return hid_keycodes.DEFAULT_KEYMAP.get(key_id)
        et = entry.get("type")
        if et == "remap_hid":
            mod = entry.get("mod", 0)
            kc = entry.get("keycode", 0)
            if isinstance(mod, int) and isinstance(kc, int):
                return (mod, kc)
        elif et == "remap":
            to = entry.get("to")
            if isinstance(to, int):
                return hid_keycodes.DEFAULT_KEYMAP.get(to)
        elif et == "disable":
            return None
        return None

    def _invalidate_caches(self) -> None:
        """Invalidate all profile-dependent caches. Call after any profile/mapping change."""
        self._conflict_cache = None
        self._conflict_hotspot_cache = None
        self._key_id_to_hotspot_cache = None

    def _get_hotspot_name(self, key_id: int) -> str:
        """Fast cached reverse lookup: key_id → hotspot name."""
        if self._key_id_to_hotspot_cache is None:
            hs = self._keymap_hotspots()
            self._key_id_to_hotspot_cache = {v: k for k, v in hs.items()}
        return self._key_id_to_hotspot_cache.get(key_id, f"key_id={key_id}")

    def _detect_conflicts(self) -> Dict[str, List[str]]:
        """Return a dict mapping output key name → list of hotspot names that produce it. Cached."""
        if self._conflict_cache is not None:
            return self._conflict_cache
        hs_bindings = self._keymap_hotspots()
        output_map: Dict[str, List[str]] = {}
        for name, key_id in hs_bindings.items():
            out = self._get_mapping_output(key_id)
            if out is None:
                continue
            label = hid_keycodes.hid_to_name(out[0], out[1])
            output_map.setdefault(label, []).append(name)
        self._conflict_cache = {k: v for k, v in output_map.items() if len(v) > 1}
        # Build conflict hotspot set
        conflict_hs: set[str] = set()
        for names in self._conflict_cache.values():
            conflict_hs.update(names)
        self._conflict_hotspot_cache = conflict_hs
        return self._conflict_cache

    def _keymap_redraw(self) -> None:
        t0 = time.monotonic() if self._perf_enabled else 0.0
        c = self._keymap_canvas
        if not c:
            return

        self._keymap_dirty = False

        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)

        # Determine if a full rebuild is needed (layout change) or just a color/pulse update.
        need_full = (w, h) != self._keymap_last_canvas_size or not self._keymap_canvas_items

        if need_full:
            c.delete("all")
            self._keymap_canvas_items = {}
            self._keymap_bg_item = None
            self._keymap_last_canvas_size = (w, h)

        if not self._keymap_img_base:
            state_name = self._keymap_img_state
            msg = (
                f"Joy-Con image for state '{state_name}' not found"
                if not self._keymap_img_path
                else f"Failed to load Joy-Con image for state '{state_name}'"
            )
            if need_full:
                c.create_text(w // 2, h // 2, text=msg, fill=self._colors.get("muted", "#666"))
            self._keymap_hotspot_px = {}
            return

        base_w = self._keymap_img_base.width()
        base_h = self._keymap_img_base.height()
        factor = max(1, int(math.ceil(base_w / max(1, w))), int(math.ceil(base_h / max(1, h))))

        if need_full or factor != self._keymap_last_scale_factor:
            self._keymap_last_scale_factor = factor
            try:
                self._keymap_img_scaled = self._keymap_img_base.subsample(factor, factor)
            except Exception:
                self._keymap_img_scaled = self._keymap_img_base

        img_w = self._keymap_img_scaled.width()
        img_h = self._keymap_img_scaled.height()
        ox = (w - img_w) / 2.0
        oy = (h - img_h) / 2.0

        if need_full:
            self._keymap_bg_item = c.create_image(ox, oy, image=self._keymap_img_scaled, anchor="nw")

        hs_bindings = self._keymap_hotspots()
        conflicts = self._detect_conflicts()
        conflict_hotspots = self._conflict_hotspot_cache or set()

        # Update conflict label and fix button (only on full rebuild to avoid flicker)
        if need_full:
            if conflicts:
                parts = [f"{key}: {', '.join(names)}" for key, names in conflicts.items()]
                self._conflict_var.set("Conflicts: " + "; ".join(parts))
                try:
                    self._conflict_fix_btn.pack(padx=8, anchor="w", pady=(0, 4))
                except Exception:
                    pass
            else:
                self._conflict_var.set("")
                try:
                    self._conflict_fix_btn.pack_forget()
                except Exception:
                    pass

        self._keymap_hotspot_px = {}
        radius = max(14, int(min(img_w, img_h) * 0.02))

        for name, nx, ny in KEYMAP_HOTSPOTS:
            px = ox + nx * img_w
            py = oy + ny * img_h
            self._keymap_hotspot_px[name] = (px, py)

            selected = (name == self._keymap_selected_name)
            bound_key_id = hs_bindings.get(name)
            is_active = bound_key_id is not None and bound_key_id in self._active_key_ids
            is_conflict = name in conflict_hotspots
            has_mapping = False
            mapping_label = ""

            if bound_key_id is not None:
                try:
                    prof = self._current_profile()
                    entry = prof.get("mappings", {}).get(str(bound_key_id))
                    if isinstance(entry, dict):
                        has_mapping = True
                        et = entry.get("type", "")
                        if et == "remap_hid":
                            mapping_label = hid_keycodes.hid_to_name(
                                entry.get("mod", 0), entry.get("keycode", 0)
                            )
                        elif et == "remap":
                            to = entry.get("to", 0)
                            dk = hid_keycodes.DEFAULT_KEYMAP.get(to)
                            mapping_label = hid_keycodes.hid_to_name(dk[0], dk[1]) if dk else f"→{to}"
                        elif et == "disable":
                            mapping_label = "OFF"
                        elif et == "macro":
                            mapping_label = f"M:{entry.get('id', '?')}"
                        elif et == "tap_hold":
                            hold = entry.get("hold", {})
                            hkc = hold.get("keycode", 0) if isinstance(hold, dict) else 0
                            hmod = hold.get("mod", 0) if isinstance(hold, dict) else 0
                            mapping_label = f"T/H:{hid_keycodes.hid_to_name(hmod, hkc)}"
                    else:
                        # Passthrough
                        dk = hid_keycodes.DEFAULT_KEYMAP.get(bound_key_id)
                        if dk:
                            mapping_label = hid_keycodes.hid_to_name(dk[0], dk[1])
                except Exception:
                    pass

            # Color coding
            if is_active:
                base_active = self._colors.get("accent2", "#3a8a5c")
                bright = _blend_hex(base_active, "#ffffff", 0.4)
                fill = _blend_hex(base_active, bright, self._pulse_phase)
                outline = fill
            elif is_conflict:
                fill = self._colors.get("danger", "#c84848")
                outline = self._colors.get("danger", "#c84848")
            elif selected:
                fill = self._colors.get("accent", "#4a7cc8")
                outline = self._colors.get("accent", "#4a7cc8")
            elif has_mapping:
                fill = self._colors.get("warning", "#b89030")
                outline = self._colors.get("warning", "#b89030")
            else:
                fill = self._colors.get("panel", "#fff")
                outline = self._colors.get("border", "#333")

            text_col = _contrast_on(fill)
            label = name
            if mapping_label:
                label = f"{name}\n{mapping_label}"

            existing = self._keymap_canvas_items.get(name)
            if existing and not need_full:
                # Update in-place: recolor oval + pulse ring + text
                oval_id, text_id, search_id, pulse_id = existing
                c.itemconfigure(oval_id, outline=outline, fill=fill)
                c.itemconfigure(text_id, text=label, fill=text_col)

                # Update pulse ring
                if is_active:
                    pulse_r = radius + int(6 * self._pulse_phase)
                    pulse_col = _blend_hex(fill, self._colors.get("bg", "#e8d8b8"), 0.5)
                    if pulse_id:
                        c.coords(pulse_id, px - pulse_r, py - pulse_r, px + pulse_r, py + pulse_r)
                        c.itemconfigure(pulse_id, outline=pulse_col, state="normal")
                    else:
                        pulse_id = c.create_oval(
                            px - pulse_r, py - pulse_r, px + pulse_r, py + pulse_r,
                            outline=pulse_col, width=2, dash=(4, 4),
                        )
                        self._keymap_canvas_items[name] = (oval_id, text_id, search_id, pulse_id)
                elif pulse_id:
                    c.itemconfigure(pulse_id, state="hidden")

                # Search highlight
                is_search_match = name in self._search_matches
                if search_id:
                    c.itemconfigure(search_id, state="normal" if is_search_match else "hidden")
            else:
                # Full create
                is_search_match = name in self._search_matches
                search_id = None
                if is_search_match:
                    sr = radius + 5
                    search_id = c.create_oval(
                        px - sr, py - sr, px + sr, py + sr,
                        outline=self._colors.get("accent", "#4a7cc8"), width=3, dash=(6, 2),
                    )

                oval_id = c.create_oval(
                    px - radius, py - radius, px + radius, py + radius,
                    outline=outline, width=2, fill=fill,
                )

                pulse_id = None
                if is_active:
                    pulse_r = radius + int(6 * self._pulse_phase)
                    pulse_col = _blend_hex(fill, self._colors.get("bg", "#e8d8b8"), 0.5)
                    pulse_id = c.create_oval(
                        px - pulse_r, py - pulse_r, px + pulse_r, py + pulse_r,
                        outline=pulse_col, width=2, dash=(4, 4),
                    )

                text_id = c.create_text(
                    px, py, text=label, fill=text_col,
                    font=(self._typo.get("font_family", "Segoe UI"), 8, "bold"),
                )

                self._keymap_canvas_items[name] = (oval_id, text_id, search_id, pulse_id)

        if self._perf_enabled:
            dt = time.monotonic() - t0
            self._perf_redraw_times.append(dt)
            if len(self._perf_redraw_times) > 60:
                self._perf_redraw_times = self._perf_redraw_times[-60:]

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

    # ── Ghost labels on hover ──
    _hover_ghost_name: Optional[str] = None

    def _keymap_on_motion(self, e: tk.Event) -> None:
        """Show a ghost tooltip near the hovered hotspot."""
        name = self._keymap_pick_hotspot(float(getattr(e, "x", 0)), float(getattr(e, "y", 0)))
        if name == self._hover_ghost_name:
            return
        self._hover_ghost_name = name
        c = self._keymap_canvas
        c.delete("ghost_tip")
        if name is None:
            return
        pos = self._keymap_hotspot_px.get(name)
        if pos is None:
            return
        px, py = pos
        hs = self._keymap_hotspots()
        kid = hs.get(name)
        tip_parts = [name]
        if kid is not None:
            try:
                prof = self._current_profile()
                entry = prof.get("mappings", {}).get(str(kid))
                if isinstance(entry, dict):
                    et = entry.get("type", "")
                    if et == "remap_hid":
                        tip_parts.append(hid_keycodes.hid_to_name(entry.get("mod", 0), entry.get("keycode", 0)))
                    elif et == "disable":
                        tip_parts.append("Disabled")
                    elif et == "macro":
                        tip_parts.append(f"Macro {entry.get('id', '?')}")
                    elif et == "tap_hold":
                        tip_parts.append("Tap/Hold")
                else:
                    dk = hid_keycodes.DEFAULT_KEYMAP.get(kid)
                    if dk:
                        tip_parts.append(hid_keycodes.hid_to_name(dk[0], dk[1]))
            except Exception:
                pass
        tip_text = " → ".join(tip_parts)
        c.create_text(
            px, py - 26, text=tip_text, tags="ghost_tip",
            fill=self._colors.get("muted", "#888"),
            font=(self._typo.get("font_family", "Segoe UI"), 7, "italic"),
        )

    def _keymap_on_click(self, e: tk.Event) -> None:
        name = self._keymap_pick_hotspot(float(getattr(e, "x", 0)), float(getattr(e, "y", 0)))
        if not name:
            return

        self._keymap_selected_name = name
        hs = self._keymap_hotspots()
        bound = hs.get(name)
        if bound is None:
            # No key_id → auto-enter learn mode (press controller button)
            self._keymap_learn_name = name
            self._mapping_key_id.set("")
            self._keymap_status.set(
                f"[{name}] Press the controller button now to learn its key_id… (or right-click for options)"
            )
        else:
            # Has key_id → auto-enter press-to-bind mode (press keyboard key)
            self._bind_mode = True
            self._bind_hotspot = name
            self._mapping_key_id.set(str(bound))
            self._mapping_load_from_profile(int(bound))
            self._keymap_status.set(
                f"[{name}] Press a keyboard key to bind → key_id={bound}  (Escape to cancel, right-click for more)"
            )

        self._keymap_redraw()

    def _keymap_begin_learn(self) -> None:
        if not self._keymap_selected_name:
            self._keymap_status.set("Select a control first.")
            return
        self._keymap_learn_name = self._keymap_selected_name
        self._keymap_status.set(f"Learning {self._keymap_selected_name}… press that controller button now.")

    def _keymap_on_right_click(self, e: tk.Event) -> None:
        """Show a context menu for the clicked hotspot."""
        name = self._keymap_pick_hotspot(float(getattr(e, "x", 0)), float(getattr(e, "y", 0)))
        if not name:
            return

        self._keymap_selected_name = name
        self._keymap_redraw()

        hs = self._keymap_hotspots()
        bound = hs.get(name)

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label=f"Learn key_id for {name}",
            command=lambda: self._keymap_context_learn(name),
        )
        if bound is not None:
            menu.add_command(
                label=f"Bind keyboard key → {name}",
                command=lambda: self._keymap_context_bind(name),
            )
            menu.add_command(
                label=f"What should {name} do?",
                command=lambda: self._show_intent_menu(name, bound),
            )
            menu.add_separator()
            menu.add_command(
                label=f"Explain {name} mapping",
                command=lambda: self._show_explain_dialog(name),
            )
            menu.add_separator()
            menu.add_command(
                label=f"Reset {name} to passthrough",
                command=lambda: self._keymap_context_reset(name),
            )
            menu.add_command(
                label=f"Clear {name} binding",
                command=lambda: self._keymap_context_clear(name),
            )
            menu.add_command(
                label=f"Disable {name}",
                command=lambda: self._keymap_context_disable(name),
            )
            menu.add_separator()
            if name in self._locked_hotspots:
                menu.add_command(
                    label=f"Unlock {name}",
                    command=lambda: self._locked_hotspots.discard(name),
                )
            else:
                menu.add_command(
                    label=f"Lock {name} (prevent accidental changes)",
                    command=lambda: self._locked_hotspots.add(name),
                )

        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def _keymap_context_learn(self, name: str) -> None:
        self._keymap_selected_name = name
        self._keymap_learn_name = name
        self._keymap_status.set(f"[{name}] Press the controller button now…")

    def _keymap_context_bind(self, name: str) -> None:
        hs = self._keymap_hotspots()
        key_id = hs.get(name)
        if key_id is None:
            return
        self._keymap_selected_name = name
        self._bind_mode = True
        self._bind_hotspot = name
        self._mapping_key_id.set(str(key_id))
        self._keymap_status.set(f"[{name}] Press a keyboard key to bind… (Escape to cancel)")

    def _keymap_context_reset(self, name: str) -> None:
        if not self._check_lock_before_unbind(name, "reset to passthrough"):
            return
        self._keymap_selected_name = name
        self._keymap_reset_selected()

    def _keymap_context_clear(self, name: str) -> None:
        if not self._check_lock_before_unbind(name, "clear binding"):
            return
        self._keymap_selected_name = name
        self._keymap_clear_selected()

    def _keymap_context_disable(self, name: str) -> None:
        """Disable the selected hotspot's output."""
        if not self._check_lock_before_unbind(name, "disable"):
            return
        hs = self._keymap_hotspots()
        key_id = hs.get(name)
        if key_id is None:
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        mappings = prof.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
            prof["mappings"] = mappings
        mappings[str(key_id)] = {"type": "disable"}
        self._set_profile_obj(prof)
        self._keymap_status.set(f"{name} disabled.")
        self._keymap_redraw()

    # ------------------------------------------------------------------
    # Chording
    # ------------------------------------------------------------------

    def _chord_add(self) -> None:
        """Add a chord definition to the profile."""
        keys_str = self._chord_keys_var.get().strip()
        output_str = self._chord_output_var.get().strip()
        if not keys_str or not output_str:
            messagebox.showerror("Missing fields", "Enter both key_ids and output keycode.")
            return

        try:
            keys = [int(k.strip()) for k in keys_str.split(",") if k.strip()]
        except ValueError:
            messagebox.showerror("Bad key_ids", "Key IDs must be comma-separated integers.")
            return

        if len(keys) < 2:
            messagebox.showerror("Too few keys", "A chord requires at least 2 keys.")
            return

        try:
            kc = int(output_str, 0)
        except ValueError:
            messagebox.showerror("Bad keycode", "Output must be a HID keycode (integer or 0xHH).")
            return

        try:
            prof = self._current_profile()
        except Exception:
            return

        chords = prof.setdefault("chords", [])
        if not isinstance(chords, list):
            chords = []
            prof["chords"] = chords

        chords.append({
            "keys": sorted(keys),
            "action": {"type": "remap_hid", "mod": 0, "keycode": kc},
        })
        self._set_profile_obj(prof)
        self._chord_refresh_display()
        self._log_line(f"[host] Added chord: {keys} → 0x{kc:02X}")

    def _chord_clear(self) -> None:
        """Remove all chord definitions."""
        try:
            prof = self._current_profile()
        except Exception:
            return
        prof["chords"] = []
        self._set_profile_obj(prof)
        self._chord_refresh_display()
        self._log_line("[host] Cleared all chords")

    def _chord_refresh_display(self) -> None:
        """Update the chord list display."""
        try:
            prof = self._current_profile()
        except Exception:
            self._chord_list_var.set("(none)")
            return

        chords = prof.get("chords", [])
        if not isinstance(chords, list) or not chords:
            self._chord_list_var.set("(none)")
            return

        parts = []
        for ch in chords:
            keys = ch.get("keys", [])
            action = ch.get("action", {})
            kc = action.get("keycode", 0)
            mod = action.get("mod", 0)
            key_names = [str(k) for k in keys]
            out_name = hid_keycodes.hid_to_name(mod, kc)
            parts.append(f"[{'+'.join(key_names)}] → {out_name}")

        self._chord_list_var.set("  |  ".join(parts))

    # ------------------------------------------------------------------
    # Conflict auto-fix
    # ------------------------------------------------------------------

    def _conflict_auto_fix(self) -> None:
        """Resolve duplicate output bindings by keeping only the first mapping for each output."""
        conflicts = self._detect_conflicts()
        if not conflicts:
            return

        try:
            prof = self._current_profile()
        except Exception:
            return

        mappings = prof.get("mappings", {})
        if not isinstance(mappings, dict):
            return

        hs_bindings = self._keymap_hotspots()
        removed = []
        for _output_key, hotspot_names in conflicts.items():
            # Keep the first, remove the rest
            for name in hotspot_names[1:]:
                key_id = hs_bindings.get(name)
                if key_id is not None and str(key_id) in mappings:
                    del mappings[str(key_id)]
                    removed.append(name)

        self._set_profile_obj(prof)
        self._keymap_redraw()
        self._log_line(f"[host] Auto-fix: cleared duplicate mappings for {', '.join(removed)}")

    def _keymap_begin_bind(self) -> None:
        """Start press-to-bind: wait for a keyboard key press to map to the selected hotspot."""
        if not self._keymap_selected_name:
            self._keymap_status.set("Select a control first.")
            return
        hs = self._keymap_hotspots()
        bound_key_id = hs.get(self._keymap_selected_name)
        if bound_key_id is None:
            self._keymap_status.set(f"Use Learn first to assign a key_id to {self._keymap_selected_name}.")
            return
        self._bind_mode = True
        self._bind_hotspot = self._keymap_selected_name
        self._keymap_status.set(f"Press a keyboard key to bind to {self._keymap_selected_name}… (Escape to cancel)")

    def _on_keypress_bind(self, event: tk.Event) -> None:
        """Handle keyboard key press for press-to-bind mode."""
        if not self._bind_mode:
            return

        keysym = getattr(event, "keysym", "")
        if keysym == "Escape":
            self._bind_mode = False
            self._bind_hotspot = None
            self._keymap_status.set("Bind cancelled.")
            return

        hid = hid_keycodes.keysym_to_hid(keysym)
        if hid is None:
            self._keymap_status.set(f"Unrecognised key: {keysym}. Try another key, or Escape to cancel.")
            return

        mod, keycode = hid
        hotspot = self._bind_hotspot
        self._bind_mode = False
        self._bind_hotspot = None

        if not hotspot:
            return

        # Get the key_id for this hotspot
        hs = self._keymap_hotspots()
        key_id = hs.get(hotspot)
        if key_id is None:
            return

        # Apply remap_hid mapping
        try:
            prof = self._current_profile()
        except Exception:
            return

        mappings = prof.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
            prof["mappings"] = mappings

        mappings[str(key_id)] = {"type": "remap_hid", "mod": mod, "keycode": keycode}
        self._set_profile_obj(prof, undo_label=f"bind {hotspot}")

        key_name = hid_keycodes.hid_to_name(mod, keycode)
        self._keymap_status.set(f"Bound {hotspot} → {key_name}")
        self._mapping_key_id.set(str(key_id))
        self._mapping_type.set("remap_hid")
        self._keymap_redraw()
        self._play_sound("bind")

    def _keymap_reset_selected(self) -> None:
        """Remove the mapping for the currently selected hotspot (revert to passthrough)."""
        if not self._keymap_selected_name:
            self._keymap_status.set("Select a control first.")
            return
        hs = self._keymap_hotspots()
        key_id = hs.get(self._keymap_selected_name)
        if key_id is None:
            self._keymap_status.set(f"{self._keymap_selected_name} has no key_id bound.")
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        mappings = prof.get("mappings", {})
        if isinstance(mappings, dict):
            mappings.pop(str(key_id), None)
        self._set_profile_obj(prof)
        self._mapping_type.set("passthrough")
        self._keymap_status.set(f"Reset {self._keymap_selected_name} to passthrough.")
        self._keymap_redraw()

    def _profile_rename(self) -> None:
        """Rename the current profile using the Name entry field."""
        new_name = self._profile_name_var.get().strip()
        if not new_name:
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        prof["name"] = new_name
        self._set_profile_obj(prof)
        self._log_line(f"[host] Profile renamed to '{new_name}'")

    def _profile_duplicate(self) -> None:
        """Duplicate the current profile with a new name and load it into the editor."""
        try:
            prof = self._current_profile()
        except Exception:
            return
        import copy as _copy
        dup = _copy.deepcopy(prof)
        old_name = dup.get("name", "default")
        dup["name"] = f"{old_name} (copy)"
        self._set_profile_obj(dup)
        self._profile_name_var.set(dup["name"])
        self._log_line(f"[host] Duplicated profile '{old_name}' → '{dup['name']}'")

    def _profile_reset_defaults(self) -> None:
        """Reset the profile to a clean default state (keeps name)."""
        try:
            prof = self._current_profile()
        except Exception:
            prof = {}
        name = prof.get("name", "default")
        fresh = _ensure_profile_defaults({"name": name})
        self._set_profile_obj(fresh)
        self._profile_name_var.set(name)
        self._keymap_redraw()
        self._log_line(f"[host] Profile '{name}' reset to defaults.")

    # ------------------------------------------------------------------
    # Profile slot quick-select
    # ------------------------------------------------------------------

    def _slot_select(self, idx: int) -> None:
        """Select a slot, read its profile from the device, and load it."""
        self.slot_var.set(str(idx))
        # Highlight the active slot button
        for i, btn in enumerate(self._slot_buttons):
            try:
                if i == idx:
                    btn.configure(style="Primary.TButton")
                else:
                    btn.configure(style="TButton")
            except Exception:
                pass
        self._cmd_read_profile()
        self._log_line(f"[host] Selected slot {idx}")

    def _slot_read_all(self) -> None:
        """Read profile names from all 4 slots (sends 4 read commands)."""
        for i in range(4):
            self._send_cmd({"cmd": "read_profile", "slot": i})

    def _slot_update_name(self, slot: int, name: str) -> None:
        """Update the slot button label with the profile name."""
        if 0 <= slot < len(self._slot_name_vars):
            display = name[:14] if name else f"Slot {slot}"
            self._slot_name_vars[slot].set(f"{slot}: {display}")

    # ------------------------------------------------------------------
    # Safe mode (reset active slot to defaults on device)
    # ------------------------------------------------------------------

    def _cmd_safe_mode(self) -> None:
        """Reset the active slot to a clean default profile and activate it."""
        confirm = messagebox.askyesno(
            "Safe mode",
            "This will overwrite the current slot with a clean default profile "
            "and set it as active on the device.\n\n"
            "Use this if your controls become unusable.\n\n"
            "Continue?",
        )
        if not confirm:
            return

        slot = int(self.slot_var.get())
        fresh = _ensure_profile_defaults({"name": f"safe-default-{slot}"})
        self._set_profile_obj(fresh)
        self._send_cmd({"cmd": "write_profile", "slot": slot, "profile": fresh})
        self._send_cmd({"cmd": "set_active_profile", "slot": slot})
        self._log_line(f"[host] Safe mode: slot {slot} reset to defaults and activated")

    def _layer_add(self) -> None:
        """Add a new layer to the profile."""
        try:
            prof = self._current_profile()
        except Exception:
            return
        layers = prof.setdefault("layers", [])
        if not isinstance(layers, list):
            layers = []
            prof["layers"] = layers
        if len(layers) >= 4:
            messagebox.showinfo("Layer limit", "Maximum 4 layers supported.")
            return
        idx = len(layers)
        layers.append({
            "name": f"layer{idx + 1}",
            "key_id": 0,
            "mode": "hold",
            "mappings": {},
        })
        self._set_profile_obj(prof)
        self._layer_edit_index.set(idx)
        self._keymap_redraw()
        self._rebuild_layer_stack()
        self._log_line(f"[host] Added layer {idx + 1}")

    def _layer_remove(self) -> None:
        """Remove the currently selected layer."""
        idx = self._layer_edit_index.get()
        if idx < 0:
            messagebox.showinfo("Select layer", "Select a layer (not Base) to remove.")
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        layers = prof.get("layers", [])
        if not isinstance(layers, list) or idx >= len(layers):
            return
        removed = layers.pop(idx)
        self._set_profile_obj(prof)
        self._layer_edit_index.set(-1)
        self._keymap_redraw()
        self._rebuild_layer_stack()
        self._log_line(f"[host] Removed layer '{removed.get('name', idx)}'")

    def _layer_apply_config(self) -> None:
        """Apply the layer configuration (activation key_id, mode, name) from the UI."""
        idx = self._layer_edit_index.get()
        if idx < 0:
            return
        try:
            prof = self._current_profile()
        except Exception:
            return
        layers = prof.get("layers", [])
        if not isinstance(layers, list) or idx >= len(layers):
            return
        try:
            key_id = int(self._layer_key_id_var.get())
        except ValueError:
            messagebox.showerror("Bad key_id", "Activation key_id must be an integer.")
            return
        layers[idx]["key_id"] = key_id
        layers[idx]["mode"] = self._layer_mode_var.get() or "hold"
        name = self._layer_name_var.get().strip()
        if name:
            layers[idx]["name"] = name
        self._set_profile_obj(prof)
        self._log_line(f"[host] Layer {idx + 1} config updated")

    def _rebuild_layer_stack(self) -> None:
        """Rebuild the visual layer stack summary (shows mapping counts per layer)."""
        frame = getattr(self, "_layer_stack_frame", None)
        if frame is None:
            return
        for lbl in self._layer_stack_labels:
            lbl.destroy()
        self._layer_stack_labels.clear()

        try:
            prof = self._current_profile()
        except Exception:
            return
        layers = prof.get("layers", [])
        if not isinstance(layers, list):
            layers = []
        base_count = len(prof.get("mappings", {}))

        desc = f"  Base  ({base_count} mappings)"
        lbl = ttk.Label(frame, text=desc, relief="ridge", padding=(6, 2))
        lbl.pack(side=tk.LEFT, padx=(0, 4))
        self._layer_stack_labels.append(lbl)

        for i, layer in enumerate(layers):
            name = layer.get("name", f"layer{i+1}")
            mode = layer.get("mode", "hold")
            cnt = len(layer.get("mappings", {}))
            txt = f"  {name} ({mode}, {cnt} overrides)  "
            lbl = ttk.Label(frame, text=txt, relief="groove", padding=(6, 2))
            lbl.pack(side=tk.LEFT, padx=(0, 4))
            self._layer_stack_labels.append(lbl)

    def _build_input_test_tab(self) -> None:
        """Build the Input Test tab: live event log + visual timeline + active key summary."""
        top = ttk.Frame(self.tab_input_test)
        top.pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Label(top, text="Active keys:").pack(side=tk.LEFT)
        ttk.Label(top, textvariable=self._input_test_active_var, wraplength=700, justify="left").pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(top, text="Clear log", command=self._input_test_clear).pack(side=tk.RIGHT)

        # ── Performance profiling toggle ──
        perf_row = ttk.Frame(self.tab_input_test)
        perf_row.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._perf_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(perf_row, text="Show performance stats", variable=self._perf_var,
                        command=self._toggle_perf).pack(side=tk.LEFT)
        self._perf_stats_var = tk.StringVar(value="")
        self._perf_label = ttk.Label(perf_row, textvariable=self._perf_stats_var, style="Muted.TLabel")
        self._perf_label.pack(side=tk.LEFT, padx=(12, 0))

        # ── Visual event timeline ──
        tl_frame = ttk.LabelFrame(self.tab_input_test, text="Event timeline (last 5 seconds)")
        tl_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._timeline_canvas = tk.Canvas(tl_frame, height=60, highlightthickness=1)
        self._timeline_canvas.pack(fill=tk.X, padx=4, pady=4)
        try:
            self._timeline_canvas.configure(
                bg=self._colors["panel2"],
                highlightbackground=self._colors["border"],
            )
        except Exception:
            pass

        ttk.Label(self.tab_input_test, text="Event log (newest first)").pack(anchor="w", padx=8)
        self._input_test_log = ScrolledText(self.tab_input_test, height=16, state="disabled")
        self._input_test_log.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self._theme_scrolled_text(self._input_test_log)

        # Refresh timeline periodically
        self.after(200, self._timeline_redraw_tick)

    def _input_test_clear(self) -> None:
        if not hasattr(self, "_input_test_log"):
            return
        self._input_test_log.configure(state="normal")
        self._input_test_log.delete("1.0", "end")
        self._input_test_log.configure(state="disabled")

    def _input_test_append(self, line: str) -> None:
        if not hasattr(self, "_input_test_log"):
            return
        log_w = self._input_test_log
        log_w.configure(state="normal")
        log_w.insert("1.0", line + "\n")
        # Trim to 500 lines
        total = int(log_w.index("end-1c").split(".")[0])
        if total > 500:
            log_w.delete(f"{501}.0", "end")
        log_w.configure(state="disabled")

    def _timeline_add_event(self, label: str, color: str) -> None:
        """Record an event for the visual timeline."""
        self._event_timeline.append((time.time(), label, color))
        # Trim old events (>10 seconds)
        cutoff = time.time() - 10.0
        self._event_timeline = [(t, l, c) for t, l, c in self._event_timeline if t > cutoff]

    def _timeline_redraw_tick(self) -> None:
        """Periodically redraw the event timeline canvas — skip if no changes."""
        now = time.time()
        # Only redraw if events changed or old events expired (every ~1s)
        if (len(self._event_timeline) != self._timeline_last_count
                or now - self._timeline_last_draw_time > 1.0):
            self._timeline_redraw()
            self._timeline_last_count = len(self._event_timeline)
            self._timeline_last_draw_time = now
        self.after(200, self._timeline_redraw_tick)

    def _timeline_redraw(self) -> None:
        """Draw the event timeline canvas showing recent events."""
        c = self._timeline_canvas
        if not c:
            return
        c.delete("all")

        w = max(c.winfo_width(), 200)
        h = max(c.winfo_height(), 50)
        now = time.time()
        window_sec = 5.0  # show last 5 seconds
        pad = 4

        # Draw time axis
        axis_col = self._colors.get("border", "#666")
        c.create_line(pad, h - 12, w - pad, h - 12, fill=axis_col)
        for sec in range(int(window_sec) + 1):
            x = pad + (1.0 - sec / window_sec) * (w - 2 * pad)
            c.create_line(x, h - 15, x, h - 9, fill=axis_col)
            c.create_text(x, h - 4, text=f"-{sec}s", fill=self._colors.get("muted", "#999"),
                         font=("Consolas", 7))

        # Trim expired
        cutoff = now - window_sec
        self._event_timeline = [(t, l, cl) for t, l, cl in self._event_timeline if t > cutoff]

        # Draw events as colored marks
        for t, label, color in self._event_timeline:
            age = now - t
            x = pad + (1.0 - age / window_sec) * (w - 2 * pad)
            if x < pad or x > w - pad:
                continue
            c.create_line(x, pad, x, h - 18, fill=color, width=2)
            c.create_text(x, pad + 6, text=label, fill=color,
                         font=(self._typo.get("font_family", "Segoe UI"), 7), anchor="n")

    # ------------------------------------------------------------------
    # Performance profiling display
    # ------------------------------------------------------------------

    def _toggle_perf(self) -> None:
        """Toggle performance stats collection and display."""
        self._perf_enabled = self._perf_var.get()
        if self._perf_enabled:
            self._perf_redraw_times.clear()
            self._perf_input_times.clear()
            self._perf_stats_var.set("Collecting...")
            self._perf_update_tick()
        else:
            self._perf_stats_var.set("")

    def _perf_update_tick(self) -> None:
        """Periodically update profiling stats display."""
        if not self._perf_enabled:
            return
        parts: list[str] = []
        if self._perf_redraw_times:
            recent = self._perf_redraw_times[-50:]
            avg_ms = sum(recent) / len(recent) * 1000
            max_ms = max(recent) * 1000
            parts.append(f"Redraw: avg {avg_ms:.1f}ms, max {max_ms:.1f}ms ({len(recent)} samples)")
        if self._perf_input_times:
            recent = self._perf_input_times[-50:]
            lats = [proc - recv for recv, proc in recent]
            avg_lat = sum(lats) / len(lats) * 1000
            max_lat = max(lats) * 1000
            parts.append(f"Input: avg {avg_lat:.1f}ms, max {max_lat:.1f}ms")
        self._perf_stats_var.set("  |  ".join(parts) if parts else "Collecting...")
        self.after(500, self._perf_update_tick)

    # ------------------------------------------------------------------
    # Mouse tab  (M913 Impact Elite configuration)
    # ------------------------------------------------------------------

    def _build_mouse_tab(self) -> None:
        """Build the Mouse tab: M913 device selection, buttons, DPI, LED, polling."""
        parent = self.tab_mouse

        # ── Instance state ──
        self._m913_devices: List[m913_device.M913DeviceInfo] = []
        self._m913_open_devs: Dict[str, m913_device.M913Device] = {}  # device_id → open device
        self._m913_profile = m913_device.M913Profile()
        self._m913_button_vars: Dict[str, tk.StringVar] = {}
        self._m913_dpi_vars: List[tk.IntVar] = []
        self._m913_dpi_en_vars: List[tk.BooleanVar] = []
        self._m913_registry = m913_device.load_device_registry()

        # ── Top bar: device selector + scan ──
        dev_frame = ttk.LabelFrame(parent, text="M913 Device")
        dev_frame.pack(fill=tk.X, padx=6, pady=(6, 3))

        row = ttk.Frame(dev_frame)
        row.pack(fill=tk.X, padx=6, pady=4)

        ttk.Label(row, text="Device:").pack(side=tk.LEFT)
        self._m913_dev_var = tk.StringVar()
        self._m913_dev_combo = ttk.Combobox(row, textvariable=self._m913_dev_var,
                                            state="readonly", width=36)
        self._m913_dev_combo.pack(side=tk.LEFT, padx=(4, 6))
        self._m913_dev_combo.bind("<<ComboboxSelected>>", lambda _: self._m913_on_device_selected())

        ttk.Button(row, text="Scan", command=self._m913_scan_devices).pack(side=tk.LEFT, padx=2)
        ttk.Button(row, text="Apply", command=self._m913_apply_config).pack(side=tk.LEFT, padx=2)

        if not m913_device.HID_AVAILABLE:
            ttk.Label(dev_frame, text="⚠ hidapi not installed — install with: pip install hidapi",
                      foreground=self._colors.get("danger", "red")).pack(padx=6, pady=2)

        # ── Sister profile linking ──
        sister_row = ttk.Frame(dev_frame)
        sister_row.pack(fill=tk.X, padx=6, pady=(0, 4))
        ttk.Label(sister_row, text="Link to Joy-Con slot:").pack(side=tk.LEFT)
        self._m913_sister_var = tk.StringVar(value="None")
        sister_cb = ttk.Combobox(sister_row, textvariable=self._m913_sister_var,
                                 values=["None", "Slot 1", "Slot 2", "Slot 3", "Slot 4"],
                                 state="readonly", width=10)
        sister_cb.pack(side=tk.LEFT, padx=4)
        sister_cb.bind("<<ComboboxSelected>>", lambda _: self._m913_on_sister_changed())

        # ── Layout mode (Stock M913 vs IncediusMod) ──
        layout_row = ttk.Frame(dev_frame)
        layout_row.pack(fill=tk.X, padx=6, pady=(0, 4))
        ttk.Label(layout_row, text="Layout:").pack(side=tk.LEFT)
        self._m913_layout_var = tk.StringVar(value=self._m913_profile.layout)
        layout_display = {"stock": "Stock M913", "incedius": "IncediusMod"}
        self._m913_layout_display = layout_display
        self._m913_layout_reverse = {v: k for k, v in layout_display.items()}
        layout_cb = ttk.Combobox(layout_row, textvariable=self._m913_layout_var,
                                 values=list(layout_display.values()),
                                 state="readonly", width=14)
        layout_cb.set(layout_display.get(self._m913_profile.layout, "Stock M913"))
        layout_cb.pack(side=tk.LEFT, padx=4)
        layout_cb.bind("<<ComboboxSelected>>", lambda _: self._m913_on_layout_changed())

        self._m913_edit_layout_btn = ttk.Button(
            layout_row, text="Edit Map\u2026",
            command=self._m913_edit_incedius_map)
        self._m913_edit_layout_btn.pack(side=tk.LEFT, padx=4)
        # Only enable when IncediusMod is selected
        self._m913_edit_layout_btn.state(
            ["!disabled"] if self._m913_profile.layout == "incedius" else ["disabled"])

        # ── M913 overlay image ──
        self._m913_overlay_canvas = tk.Canvas(parent, height=220, highlightthickness=1)
        self._m913_overlay_canvas.pack(fill=tk.X, padx=6, pady=(3, 3))
        try:
            self._m913_overlay_canvas.configure(
                bg=self._colors.get("panel2", "#f2e8d0"),
                highlightbackground=self._colors.get("border", "#b09878"),
            )
        except Exception:
            pass
        self._m913_overlay_canvas.bind("<Configure>", lambda _e: self._m913_redraw_overlay())
        self._m913_img_paths = self._find_m913_png_variants()
        self._m913_set_image_state("none")

        # ── Scrollable content ──
        canvas_wrap = ttk.Frame(parent)
        canvas_wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=3)

        m_canvas = tk.Canvas(canvas_wrap, highlightthickness=0,
                             bg=self._colors.get("panel", "#f2e8d0"))
        m_scroll = ttk.Scrollbar(canvas_wrap, orient=tk.VERTICAL, command=m_canvas.yview)
        m_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        m_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        m_canvas.configure(yscrollcommand=m_scroll.set)

        inner = ttk.Frame(m_canvas)
        m_canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: m_canvas.configure(scrollregion=m_canvas.bbox("all")))
        m_canvas.bind_all("<MouseWheel>", lambda e: m_canvas.yview_scroll(-e.delta // 120, "units"))

        # ── Button mapping ──
        btn_frame = ttk.LabelFrame(inner, text="Button Mapping (16 buttons)")
        btn_frame.pack(fill=tk.X, padx=4, pady=(4, 2))

        action_choices = m913_device.ALL_ACTIONS + m913_device.ALL_KEY_NAMES

        self._m913_button_labels: Dict[str, ttk.Label] = {}
        display_names = self._m913_resolved_display_names(self._m913_profile.layout)
        for i, btn_name in enumerate(m913_device.BUTTON_ORDER):
            r = ttk.Frame(btn_frame)
            r.pack(fill=tk.X, padx=4, pady=1)
            display = display_names.get(btn_name, btn_name)
            lbl = ttk.Label(r, text=f"{display}:", width=14, anchor="w")
            lbl.pack(side=tk.LEFT)
            self._m913_button_labels[btn_name] = lbl
            var = tk.StringVar(value=self._m913_profile.buttons.get(btn_name, "none"))
            self._m913_button_vars[btn_name] = var
            cb = ttk.Combobox(r, textvariable=var, values=action_choices, width=24)
            cb.pack(side=tk.LEFT, padx=4)

        # ── DPI settings ──
        dpi_frame = ttk.LabelFrame(inner, text="DPI (5 levels, 100–16000)")
        dpi_frame.pack(fill=tk.X, padx=4, pady=2)

        self._m913_dpi_vars = []
        self._m913_dpi_en_vars = []
        for i in range(5):
            r = ttk.Frame(dpi_frame)
            r.pack(fill=tk.X, padx=4, pady=1)
            en_var = tk.BooleanVar(value=self._m913_profile.dpi_enabled[i])
            self._m913_dpi_en_vars.append(en_var)
            ttk.Checkbutton(r, variable=en_var).pack(side=tk.LEFT)
            ttk.Label(r, text=f"Level {i + 1}:").pack(side=tk.LEFT, padx=(4, 0))
            dpi_var = tk.IntVar(value=self._m913_profile.dpi_values[i])
            self._m913_dpi_vars.append(dpi_var)
            sb = ttk.Spinbox(r, from_=100, to=16000, increment=100,
                             textvariable=dpi_var, width=8)
            sb.pack(side=tk.LEFT, padx=4)

        # ── LED settings ──
        led_frame = ttk.LabelFrame(inner, text="LED")
        led_frame.pack(fill=tk.X, padx=4, pady=2)

        lr1 = ttk.Frame(led_frame)
        lr1.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(lr1, text="Mode:").pack(side=tk.LEFT)
        self._m913_led_mode_var = tk.StringVar(value=self._m913_profile.led_mode)
        led_mode_cb = ttk.Combobox(lr1, textvariable=self._m913_led_mode_var,
                                   values=["off", "steady", "respiration", "rainbow"],
                                   state="readonly", width=14)
        led_mode_cb.pack(side=tk.LEFT, padx=4)

        ttk.Label(lr1, text="Color (#hex):").pack(side=tk.LEFT, padx=(8, 0))
        self._m913_led_color_var = tk.StringVar(value=f"{self._m913_profile.led_color:06x}")
        ttk.Entry(lr1, textvariable=self._m913_led_color_var, width=8).pack(side=tk.LEFT, padx=4)

        lr2 = ttk.Frame(led_frame)
        lr2.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(lr2, text="Brightness:").pack(side=tk.LEFT)
        self._m913_led_bright_var = tk.IntVar(value=self._m913_profile.led_brightness)
        ttk.Scale(lr2, from_=0, to=255, variable=self._m913_led_bright_var,
                  orient=tk.HORIZONTAL, length=120).pack(side=tk.LEFT, padx=4)
        ttk.Label(lr2, text="Speed (1-5):").pack(side=tk.LEFT, padx=(8, 0))
        self._m913_led_speed_var = tk.IntVar(value=self._m913_profile.led_speed)
        ttk.Spinbox(lr2, from_=1, to=5, textvariable=self._m913_led_speed_var,
                     width=4).pack(side=tk.LEFT, padx=4)

        # ── Polling rate ──
        poll_frame = ttk.LabelFrame(inner, text="Polling Rate")
        poll_frame.pack(fill=tk.X, padx=4, pady=2)

        pr = ttk.Frame(poll_frame)
        pr.pack(fill=tk.X, padx=4, pady=2)
        self._m913_poll_var = tk.IntVar(value=self._m913_profile.polling_rate)
        for hz in (125, 250, 500, 1000):
            ttk.Radiobutton(pr, text=f"{hz} Hz", value=hz,
                            variable=self._m913_poll_var).pack(side=tk.LEFT, padx=6)

        # ── Profile save/load ──
        prof_frame = ttk.LabelFrame(inner, text="M913 Profile")
        prof_frame.pack(fill=tk.X, padx=4, pady=(2, 6))

        pfr = ttk.Frame(prof_frame)
        pfr.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(pfr, text="Name:").pack(side=tk.LEFT)
        self._m913_prof_name_var = tk.StringVar(value=self._m913_profile.name)
        ttk.Entry(pfr, textvariable=self._m913_prof_name_var, width=20).pack(side=tk.LEFT, padx=4)

        ttk.Button(pfr, text="Save", command=self._m913_save_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(pfr, text="Load", command=self._m913_load_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(pfr, text="Delete", command=self._m913_delete_profile).pack(side=tk.LEFT, padx=2)

        # ── Status label ──
        self._m913_status_var = tk.StringVar(value="Ready — click Scan to detect M913 devices")
        ttk.Label(parent, textvariable=self._m913_status_var).pack(anchor="w", padx=6, pady=(0, 6))

        # Auto-scan on tab open
        self.after(200, self._m913_scan_devices)

    # ------------------------------------------------------------------
    # Help tab
    # ------------------------------------------------------------------

    def _build_help_tab(self) -> None:
        """Build the Help tab: pinout reference diagram."""
        parent = self.tab_help

        ttk.Label(parent, text="Board Pinout Reference",
                  font=("TkDefaultFont", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        ttk.Label(parent, text="Arduino Nano ESP32-S3 (USB HID Keyboard)  ·  NodeMCU ESP32-WROOM-32 (BT Host)",
                  foreground=self._colors.get("muted", "#666")).pack(anchor="w", padx=6, pady=(0, 4))

        # Scrollable canvas for the pinout image
        canvas_wrap = ttk.Frame(parent)
        canvas_wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=3)

        h_scroll = ttk.Scrollbar(canvas_wrap, orient=tk.HORIZONTAL)
        v_scroll = ttk.Scrollbar(canvas_wrap, orient=tk.VERTICAL)
        pinout_canvas = tk.Canvas(canvas_wrap, highlightthickness=0,
                                  bg=self._colors.get("panel", "#f2e8d0"),
                                  xscrollcommand=h_scroll.set,
                                  yscrollcommand=v_scroll.set)
        h_scroll.configure(command=pinout_canvas.xview)
        v_scroll.configure(command=pinout_canvas.yview)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        pinout_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Locate and load pinouts.png
        self._help_pinout_base: Optional[tk.PhotoImage] = None
        search_roots = _joycons_search_roots()
        for root in search_roots:
            candidate = root / "pinouts.png"
            try:
                if candidate.exists():
                    self._help_pinout_base = tk.PhotoImage(file=str(candidate))
                    break
            except Exception:
                continue

        if self._help_pinout_base:
            img_w = self._help_pinout_base.width()
            img_h = self._help_pinout_base.height()
            pinout_canvas.create_image(0, 0, image=self._help_pinout_base, anchor="nw")
            pinout_canvas.configure(scrollregion=(0, 0, img_w, img_h))
        else:
            pinout_canvas.create_text(200, 100, text="pinouts.png not found",
                                      fill=self._colors.get("muted", "#666"))

        # Mouse-wheel scrolling
        def _on_mousewheel(event: Any) -> None:
            pinout_canvas.yview_scroll(-event.delta // 120, "units")

        def _on_shift_mousewheel(event: Any) -> None:
            pinout_canvas.xview_scroll(-event.delta // 120, "units")

        pinout_canvas.bind("<MouseWheel>", _on_mousewheel)
        pinout_canvas.bind("<Shift-MouseWheel>", _on_shift_mousewheel)

    # ── M913 helpers ──

    def _m913_scan_devices(self) -> None:
        """Scan for connected M913 mice."""
        self._m913_devices = m913_device.M913Device.enumerate()
        names = [d.display_name for d in self._m913_devices]
        self._m913_dev_combo["values"] = names
        if names:
            self._m913_dev_combo.current(0)
            self._m913_status_var.set(f"Found {len(names)} M913 device(s)")
            self._m913_set_image_state("connected")
        else:
            self._m913_dev_var.set("")
            self._m913_status_var.set("No M913 devices found — is the receiver plugged in?")
            self._m913_set_image_state("none")

    def _m913_on_device_selected(self) -> None:
        """When a device is selected in the combo, load any saved profile."""
        idx = self._m913_dev_combo.current()
        if idx < 0 or idx >= len(self._m913_devices):
            return
        dev_info = self._m913_devices[idx]
        dev_id = dev_info.device_id
        reg = self._m913_registry.get(dev_id, {})
        linked_profile = reg.get("profile")
        if linked_profile:
            try:
                self._m913_profile = m913_device.load_profile(linked_profile)
                self._m913_ui_from_profile()
                self._m913_status_var.set(f"Loaded profile '{linked_profile}' for {dev_info.display_name}")
                return
            except Exception:
                pass
        self._m913_status_var.set(f"Selected {dev_info.display_name} (no saved profile)")

    def _m913_on_sister_changed(self) -> None:
        """Update sister slot linkage."""
        val = self._m913_sister_var.get()
        if val.startswith("Slot "):
            try:
                self._m913_profile.sister_slot = int(val.split()[-1])
            except ValueError:
                self._m913_profile.sister_slot = None
        else:
            self._m913_profile.sister_slot = None

    def _m913_on_layout_changed(self) -> None:
        """Switch button display names when layout mode changes."""
        selected = self._m913_layout_var.get()
        mode = self._m913_layout_reverse.get(selected, "stock")
        self._m913_profile.layout = mode
        # Enable/disable the Edit Map button
        if hasattr(self, "_m913_edit_layout_btn"):
            self._m913_edit_layout_btn.state(
                ["!disabled"] if mode == "incedius" else ["disabled"])
        display_names = self._m913_resolved_display_names(mode)
        for btn_name, lbl in self._m913_button_labels.items():
            lbl.configure(text=f"{display_names.get(btn_name, btn_name)}:")

    def _m913_resolved_display_names(self, mode: str) -> Dict[str, str]:
        """Return the effective display-name dict for the given layout mode.

        For 'incedius', overlays the user's custom ``incedius_map`` on top
        of the fixed names (left/right/middle/fire stay constant).
        """
        if mode == "incedius":
            names: Dict[str, str] = {
                "left": "Left Click", "right": "Right Click",
                "middle": "Middle Click", "fire": "Fire",
            }
            names.update(self._m913_profile.incedius_map)
            return names
        return dict(m913_device.BUTTON_DISPLAY_NAMES)

    def _m913_edit_incedius_map(self) -> None:
        """Open a dialog to reassign IncediusMod labels to physical M913 side buttons."""
        dlg = tk.Toplevel(self)
        dlg.title("Edit IncediusMod Button Map")
        dlg.geometry("380x460")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        ttk.Label(dlg, text="Assign each M913 side button to the matching\n"
                            "physical position on your IncediusMod mouse.",
                  justify="center").pack(padx=10, pady=(10, 6))

        frame = ttk.Frame(dlg)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        current_map = dict(self._m913_profile.incedius_map)
        combo_vars: Dict[str, tk.StringVar] = {}
        combos: Dict[str, ttk.Combobox] = {}

        for i, key in enumerate(m913_device.INCEDIUS_SIDE_KEYS):
            row = ttk.Frame(frame)
            row.pack(fill=tk.X, pady=1)
            stock_label = m913_device.BUTTON_DISPLAY_NAMES.get(key, key)
            ttk.Label(row, text=f"{stock_label}  →", width=12, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=current_map.get(key, m913_device.DEFAULT_INCEDIUS_MAP[key]))
            combo_vars[key] = var
            cb = ttk.Combobox(row, textvariable=var,
                              values=m913_device.INCEDIUS_LABEL_CHOICES,
                              state="readonly", width=14)
            cb.pack(side=tk.LEFT, padx=4)
            combos[key] = cb

        status_var = tk.StringVar(value="")
        ttk.Label(dlg, textvariable=status_var, foreground="red").pack(pady=(2, 0))

        btn_row = ttk.Frame(dlg)
        btn_row.pack(pady=(4, 10))

        def _on_reset() -> None:
            for key in m913_device.INCEDIUS_SIDE_KEYS:
                combo_vars[key].set(m913_device.DEFAULT_INCEDIUS_MAP[key])
            status_var.set("")

        def _on_save() -> None:
            new_map: Dict[str, str] = {}
            used_labels: Dict[str, str] = {}
            for key in m913_device.INCEDIUS_SIDE_KEYS:
                label = combo_vars[key].get()
                if label in used_labels:
                    status_var.set(
                        f"Duplicate: {label} is assigned to both "
                        f"{m913_device.BUTTON_DISPLAY_NAMES[used_labels[label]]} "
                        f"and {m913_device.BUTTON_DISPLAY_NAMES[key]}")
                    return
                used_labels[label] = key
                new_map[key] = label
            self._m913_profile.incedius_map = new_map
            self._m913_on_layout_changed()
            dlg.destroy()

        ttk.Button(btn_row, text="Reset to Default", command=_on_reset).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="Save", command=_on_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=6)

    def _m913_ui_to_profile(self) -> None:
        """Sync UI widget values into self._m913_profile."""
        p = self._m913_profile
        p.name = self._m913_prof_name_var.get().strip() or "Default"
        selected_layout = self._m913_layout_var.get()
        p.layout = self._m913_layout_reverse.get(selected_layout, "stock")
        for btn_name, var in self._m913_button_vars.items():
            p.buttons[btn_name] = var.get().strip().lower() or "none"
        p.dpi_values = [max(100, min(16000, v.get())) for v in self._m913_dpi_vars]
        p.dpi_enabled = [v.get() for v in self._m913_dpi_en_vars]
        p.led_mode = self._m913_led_mode_var.get()
        try:
            p.led_color = int(self._m913_led_color_var.get().strip().lstrip("#"), 16)
        except ValueError:
            p.led_color = 0x00FF00
        p.led_brightness = max(0, min(255, self._m913_led_bright_var.get()))
        p.led_speed = max(1, min(5, self._m913_led_speed_var.get()))
        p.polling_rate = self._m913_poll_var.get()

    def _m913_ui_from_profile(self) -> None:
        """Sync self._m913_profile values into UI widgets."""
        p = self._m913_profile
        self._m913_prof_name_var.set(p.name)
        for btn_name, var in self._m913_button_vars.items():
            var.set(p.buttons.get(btn_name, "none"))
        for i in range(5):
            self._m913_dpi_vars[i].set(p.dpi_values[i])
            self._m913_dpi_en_vars[i].set(p.dpi_enabled[i])
        self._m913_led_mode_var.set(p.led_mode)
        self._m913_led_color_var.set(f"{p.led_color:06x}")
        self._m913_led_bright_var.set(p.led_brightness)
        self._m913_led_speed_var.set(p.led_speed)
        self._m913_poll_var.set(p.polling_rate)
        if p.sister_slot:
            self._m913_sister_var.set(f"Slot {p.sister_slot}")
        else:
            self._m913_sister_var.set("None")
        # Layout mode
        display = self._m913_layout_display.get(p.layout, "Stock M913")
        self._m913_layout_var.set(display)
        self._m913_on_layout_changed()

    def _m913_apply_config(self) -> None:
        """Apply current UI settings to the selected M913 mouse."""
        idx = self._m913_dev_combo.current()
        if idx < 0 or idx >= len(self._m913_devices):
            self._m913_status_var.set("No device selected")
            return
        dev_info = self._m913_devices[idx]
        self._m913_ui_to_profile()

        dev = m913_device.M913Device()
        try:
            dev.open(dev_info)
            sent, errors = dev.apply_profile(self._m913_profile)
            if errors:
                self._m913_status_var.set(f"Applied with {errors} error(s) — {sent} packets sent")
            else:
                self._m913_status_var.set(f"Applied successfully — {sent} packets sent to {dev_info.display_name}")
            self._log_append(f"[M913] Config applied to {dev_info.display_name}: {sent} packets, {errors} errors")
        except Exception as e:
            self._m913_status_var.set(f"Error: {e}")
            self._log_append(f"[M913] Apply error: {e}")
        finally:
            dev.close()

    def _m913_save_profile(self) -> None:
        """Save current settings as an M913 profile."""
        self._m913_ui_to_profile()
        if not self._m913_profile.name.strip():
            self._m913_profile.name = "Default"
        try:
            path = m913_device.save_profile(self._m913_profile)
            # Update device registry
            idx = self._m913_dev_combo.current()
            if 0 <= idx < len(self._m913_devices):
                dev_id = self._m913_devices[idx].device_id
                self._m913_registry[dev_id] = {"profile": self._m913_profile.name}
                m913_device.save_device_registry(self._m913_registry)
            self._m913_status_var.set(f"Saved profile '{self._m913_profile.name}'")
            self._log_append(f"[M913] Profile saved: {self._m913_profile.name}")
        except Exception as e:
            self._m913_status_var.set(f"Save error: {e}")

    def _m913_load_profile(self) -> None:
        """Show a dialog to load a saved M913 profile."""
        saved = m913_device.list_saved_profiles()
        if not saved:
            self._m913_status_var.set("No saved M913 profiles found")
            return
        name = simpledialog.askstring("Load M913 Profile",
                                      f"Enter profile name:\nAvailable: {', '.join(saved)}",
                                      parent=self)
        if not name or name not in saved:
            return
        try:
            self._m913_profile = m913_device.load_profile(name)
            self._m913_ui_from_profile()
            self._m913_status_var.set(f"Loaded profile '{name}'")
        except Exception as e:
            self._m913_status_var.set(f"Load error: {e}")

    def _m913_delete_profile(self) -> None:
        """Delete a saved M913 profile."""
        saved = m913_device.list_saved_profiles()
        if not saved:
            self._m913_status_var.set("No saved profiles to delete")
            return
        name = simpledialog.askstring("Delete M913 Profile",
                                      f"Enter profile name to delete:\nAvailable: {', '.join(saved)}",
                                      parent=self)
        if not name or name not in saved:
            return
        if messagebox.askyesno("Confirm Delete", f"Delete M913 profile '{name}'?"):
            m913_device.delete_profile(name)
            self._m913_status_var.set(f"Deleted profile '{name}'")

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        # Save current state to redo stack
        current = self.profile_text.get("1.0", "end").strip()
        desc, snapshot = self._undo_stack.pop()
        self._redo_stack.append((desc, current))
        self._suppress_undo = True
        try:
            self.profile_text.delete("1.0", "end")
            self.profile_text.insert("1.0", snapshot)
            try:
                prof = json.loads(snapshot)
                self._refresh_macro_list()
                self._stick_load_from_profile(prof)
                self._keymap_refresh_visuals()
            except Exception:
                pass
        finally:
            self._suppress_undo = False
        self._update_undo_ui()
        self._play_sound("undo")
        self._log_line(f"[host] Undo: {desc}")

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        current = self.profile_text.get("1.0", "end").strip()
        desc, snapshot = self._redo_stack.pop()
        self._undo_stack.append((desc, current))
        self._suppress_undo = True
        try:
            self.profile_text.delete("1.0", "end")
            self.profile_text.insert("1.0", snapshot)
            try:
                prof = json.loads(snapshot)
                self._refresh_macro_list()
                self._stick_load_from_profile(prof)
                self._keymap_refresh_visuals()
            except Exception:
                pass
        finally:
            self._suppress_undo = False
        self._update_undo_ui()
        self._play_sound("undo")
        self._log_line(f"[host] Redo: {desc}")

    def _update_undo_ui(self) -> None:
        """Update undo/redo button states and history display."""
        try:
            if hasattr(self, "_undo_btn"):
                self._undo_btn.configure(state="normal" if self._undo_stack else "disabled")
            if hasattr(self, "_redo_btn"):
                self._redo_btn.configure(state="normal" if self._redo_stack else "disabled")
            if hasattr(self, "_undo_history_var"):
                if self._undo_stack:
                    last_5 = self._undo_stack[-5:]
                    lines = [f"  {d}" for d, _s in reversed(last_5)]
                    self._undo_history_var.set("History: " + " ← ".join(lines))
                else:
                    self._undo_history_var.set("History: (empty)")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Mode indicator / status bar
    # ------------------------------------------------------------------

    def _update_mode_indicator(self) -> None:
        """Update the always-visible status bar at bottom."""
        if not hasattr(self, "_mode_indicator_var"):
            return
        parts = []

        # Active slot
        try:
            parts.append(f"Slot {self.slot_var.get()}")
        except Exception:
            pass

        # Current layer
        try:
            li = self._layer_edit_index.get()
            if li < 0:
                parts.append("Base Layer")
            else:
                parts.append(f"Layer {li + 1}")
        except Exception:
            pass

        # Bind mode
        if self._bind_mode:
            parts.append("BIND MODE")
        elif self._keymap_learn_name:
            parts.append("LEARN MODE")

        # Sandbox
        if self._sandbox_active.get():
            parts.append("SANDBOX")

        # UI mode
        parts.append(f"UI: {self._ui_mode.get()}")

        # Undo depth
        if self._undo_stack:
            parts.append(f"Undo: {len(self._undo_stack)}")

        self._mode_indicator_var.set("  │  ".join(parts))

    def _mode_indicator_tick(self) -> None:
        self._update_mode_indicator()
        self.after(300, self._mode_indicator_tick)

    # ------------------------------------------------------------------
    # Adaptive UI — simple / advanced mode
    # ------------------------------------------------------------------

    def _toggle_ui_mode(self) -> None:
        if self._ui_mode.get() == "advanced":
            self._ui_mode.set("simple")
            self._ui_mode_btn.configure(text="Advanced mode")
        else:
            self._ui_mode.set("advanced")
            self._ui_mode_btn.configure(text="Simple mode")
        self._apply_ui_mode()

    def _apply_ui_mode(self) -> None:
        """Show/hide widgets based on current UI mode."""
        simple = self._ui_mode.get() == "simple"
        for w in self._advanced_widgets:
            try:
                if simple:
                    w.pack_forget()
                else:
                    w.pack(fill=tk.X, padx=8, pady=(0, 4))
            except Exception:
                pass

        # Hide/show full tabs in simple mode
        try:
            if simple:
                # Hide Macros, Stick, Share tabs (keep Profile, Controller, Input Test, Overlay)
                for tab_name in ("Macros", "Stick", "Share"):
                    for i in range(self.tabs.index("end")):
                        if self.tabs.tab(i, "text") == tab_name:
                            self.tabs.hide(i)
                            break
            else:
                # Show all tabs
                for i in range(self.tabs.index("end")):
                    self.tabs.add(self.tabs.tabs()[i])
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Sandbox mode
    # ------------------------------------------------------------------

    def _toggle_sandbox(self) -> None:
        if self._sandbox_active.get():
            # Entering sandbox: snapshot current profile
            self._sandbox_snapshot = self.profile_text.get("1.0", "end").strip()
            self._log_line("[host] Sandbox mode ON — changes are temporary")
        else:
            # Exiting sandbox without applying
            if self._sandbox_snapshot is not None:
                confirm = messagebox.askyesno(
                    "Exit Sandbox",
                    "Apply sandbox changes to the real profile?\n\n"
                    "Yes = keep changes\nNo = discard changes",
                )
                if not confirm and self._sandbox_snapshot:
                    self.profile_text.delete("1.0", "end")
                    self.profile_text.insert("1.0", self._sandbox_snapshot)
                    try:
                        prof = json.loads(self._sandbox_snapshot)
                        self._refresh_macro_list()
                        self._stick_load_from_profile(prof)
                        self._keymap_refresh_visuals()
                    except Exception:
                        pass
                    self._log_line("[host] Sandbox changes discarded")
                else:
                    self._log_line("[host] Sandbox changes applied")
            self._sandbox_snapshot = None

    # ------------------------------------------------------------------
    # Smart Search
    # ------------------------------------------------------------------

    def _on_search_changed(self, *_args: Any) -> None:
        """Filter and highlight hotspots matching the search query."""
        query = self._search_var.get().strip().lower()
        if not query:
            self._search_matches = []
            self._keymap_redraw()
            return

        hs = self._keymap_hotspots()
        matches: List[str] = []

        for name, _nx, _ny in KEYMAP_HOTSPOTS:
            # Match against hotspot name
            if query in name.lower():
                matches.append(name)
                continue

            # Match against output key name
            key_id = hs.get(name)
            if key_id is not None:
                out = self._get_mapping_output(key_id)
                if out is not None:
                    out_name = hid_keycodes.hid_to_name(out[0], out[1]).lower()
                    if query in out_name:
                        matches.append(name)
                        continue

                # Match against mapping type
                try:
                    prof = self._current_profile()
                    entry = prof.get("mappings", {}).get(str(key_id))
                    if isinstance(entry, dict):
                        et = entry.get("type", "")
                        if query in et.lower():
                            matches.append(name)
                            continue
                except Exception:
                    pass

        self._search_matches = matches
        self._keymap_redraw()

    # ------------------------------------------------------------------
    # Guided Mapping Wizard
    # ------------------------------------------------------------------

    # Common action presets for the guided wizard and intent-based mapping
    INTENT_PRESETS: List[Tuple[str, str, int, int]] = [
        # (label, description, mod, keycode)
        ("Move Forward", "W key", 0, 0x1A),
        ("Move Back", "S key", 0, 0x16),
        ("Move Left", "A key", 0, 0x04),
        ("Move Right", "D key", 0, 0x07),
        ("Jump", "Space", 0, 0x2C),
        ("Sprint", "Left Shift", 0x02, 0),
        ("Crouch", "Left Ctrl", 0x01, 0),
        ("Reload", "R key", 0, 0x15),
        ("Interact", "E key", 0, 0x08),
        ("Melee", "V key", 0, 0x19),
        ("Aim / ADS", "Right Mouse (not HID — use custom)", 0, 0),
        ("Open Map", "M key", 0, 0x10),
        ("Inventory", "Tab", 0, 0x2B),
        ("Custom key…", "Press any key to bind", 0, 0),
    ]

    def _open_guided_wizard(self) -> None:
        """Open the guided mapping setup wizard."""
        if self._guided_window is not None:
            try:
                self._guided_window.lift()
            except Exception:
                self._guided_window = None
            if self._guided_window is not None:
                return

        win = tk.Toplevel(self)
        win.title("Guided Setup — Let's set up your controller")
        win.geometry("500x400")
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_guided_wizard(win))
        self._guided_window = win

        colors = self._colors
        win.configure(bg=colors["bg"])

        self._guided_steps = [
            ("Move Forward", "Push the stick or press the button for FORWARD", "D-UP"),
            ("Move Back", "Press the button for BACK", "D-DN"),
            ("Move Left", "Press the button for LEFT", "D-L"),
            ("Move Right", "Press the button for RIGHT", "D-R"),
            ("Jump", "Press the button for JUMP", "A"),
            ("Sprint", "Press the button for SPRINT", "ZL"),
            ("Crouch", "Press the button for CROUCH", "ZR"),
        ]
        self._guided_step_idx = 0
        self._guided_results: List[Tuple[str, str, int]] = []  # (action, hotspot, key_id)

        tk.Label(
            win, text="🎮 Guided Controller Setup",
            bg=colors["bg"], fg=colors["text"],
            font=(self._typo.get("font_family", "Segoe UI"), 14, "bold"),
        ).pack(pady=(16, 8))

        self._guided_prompt_var = tk.StringVar(value="")
        self._guided_progress_var = tk.StringVar(value="")

        tk.Label(
            win, textvariable=self._guided_progress_var,
            bg=colors["bg"], fg=colors["muted"],
            font=(self._typo.get("font_family", "Segoe UI"), 9),
        ).pack()

        tk.Label(
            win, textvariable=self._guided_prompt_var,
            bg=colors["bg"], fg=colors["text"],
            font=(self._typo.get("font_family", "Segoe UI"), 12),
            wraplength=440,
        ).pack(pady=(20, 10))

        self._guided_status_var = tk.StringVar(value="Waiting for controller input…")
        tk.Label(
            win, textvariable=self._guided_status_var,
            bg=colors["bg"], fg=colors["accent2"],
            font=(self._typo.get("font_family", "Segoe UI"), 10),
        ).pack(pady=(10, 0))

        btn_frame = tk.Frame(win, bg=colors["bg"])
        btn_frame.pack(side=tk.BOTTOM, pady=(0, 16))
        ttk.Button(btn_frame, text="Skip this step", command=self._guided_skip).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="Cancel", command=lambda: self._close_guided_wizard(win)).pack(side=tk.LEFT)

        self._guided_advance_prompt()

    def _guided_advance_prompt(self) -> None:
        if self._guided_step_idx >= len(self._guided_steps):
            self._guided_finish()
            return

        action, prompt, _hotspot = self._guided_steps[self._guided_step_idx]
        total = len(self._guided_steps)
        self._guided_progress_var.set(f"Step {self._guided_step_idx + 1} of {total}")
        self._guided_prompt_var.set(prompt)
        self._guided_status_var.set("Press the controller button now…")
        # Set learn mode for the guided hotspot
        self._keymap_learn_name = _hotspot
        self._keymap_selected_name = _hotspot
        self._keymap_redraw()

    def _guided_on_input(self, key_id: int) -> None:
        """Called when a controller button is pressed during guided setup."""
        if self._guided_window is None or self._guided_step_idx >= len(self._guided_steps):
            return

        action, _prompt, hotspot = self._guided_steps[self._guided_step_idx]
        self._guided_results.append((action, hotspot, key_id))
        self._guided_status_var.set(f"Got key_id={key_id} for {action}!")

        # Bind the hotspot
        self._keymap_bind_selected(key_id)

        # Apply default mapping for this action
        defaults = {
            "Move Forward": (0, 0x1A),  # W
            "Move Back": (0, 0x16),  # S
            "Move Left": (0, 0x04),  # A
            "Move Right": (0, 0x07),  # D
            "Jump": (0, 0x2C),  # Space
            "Sprint": (0x02, 0),  # Left Shift
            "Crouch": (0x01, 0),  # Left Ctrl
        }
        if action in defaults:
            mod, kc = defaults[action]
            try:
                prof = self._current_profile()
                mappings = prof.setdefault("mappings", {})
                if not isinstance(mappings, dict):
                    mappings = {}
                    prof["mappings"] = mappings
                mappings[str(key_id)] = {"type": "remap_hid", "mod": mod, "keycode": kc}
                self._set_profile_obj(prof, undo_label=f"guided: {action}")
            except Exception:
                pass

        self._guided_step_idx += 1
        self.after(300, self._guided_advance_prompt)  # Auto-advance quickly

    def _guided_skip(self) -> None:
        self._keymap_learn_name = None
        self._guided_step_idx += 1
        self._guided_advance_prompt()

    def _guided_finish(self) -> None:
        if self._guided_window is None:
            return
        self._guided_prompt_var.set("Setup complete!")
        self._guided_status_var.set(
            f"Mapped {len(self._guided_results)} buttons. You can fine-tune in the Controller tab."
        )
        self._guided_progress_var.set("Done!")
        self._keymap_learn_name = None
        self._keymap_redraw()
        self._log_line(f"[host] Guided setup complete: {len(self._guided_results)} buttons mapped")

    def _close_guided_wizard(self, win: tk.Toplevel) -> None:
        self._keymap_learn_name = None
        self._guided_window = None
        try:
            win.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Intent-Based Mapping
    # ------------------------------------------------------------------

    def _show_intent_menu(self, hotspot: str, key_id: int) -> None:
        """Show 'What should this button do?' menu for intent-based mapping."""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="─ What should this button do? ─", state="disabled")
        menu.add_separator()

        for label, desc, mod, kc in self.INTENT_PRESETS:
            if label == "Custom key…":
                menu.add_separator()
                menu.add_command(
                    label=f"{label}  ({desc})",
                    command=lambda h=hotspot: self._keymap_context_bind(h),
                )
            elif kc == 0 and mod == 0:
                # Not a valid HID mapping (like "Aim / ADS")
                menu.add_command(label=f"{label}  ({desc})", state="disabled")
            else:
                menu.add_command(
                    label=f"{label}  →  {desc}",
                    command=lambda m=mod, k=kc, lbl=label: self._apply_intent(hotspot, key_id, m, k, lbl),
                )

        try:
            # Show at hotspot position
            px, py = self._keymap_hotspot_px.get(hotspot, (0, 0))
            cx = self._keymap_canvas.winfo_rootx() + int(px)
            cy = self._keymap_canvas.winfo_rooty() + int(py)
            menu.tk_popup(cx, cy)
        except Exception:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _apply_intent(self, hotspot: str, key_id: int, mod: int, keycode: int, label: str) -> None:
        """Apply an intent-based mapping."""
        try:
            prof = self._current_profile()
        except Exception:
            return
        mappings = prof.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
            prof["mappings"] = mappings
        mappings[str(key_id)] = {"type": "remap_hid", "mod": mod, "keycode": keycode}
        self._set_profile_obj(prof, undo_label=f"intent: {label}")
        key_name = hid_keycodes.hid_to_name(mod, keycode)
        self._keymap_status.set(f"Mapped {hotspot} → {label} ({key_name})")
        self._keymap_redraw()

    # ------------------------------------------------------------------
    # Smart Defaults
    # ------------------------------------------------------------------

    def _apply_smart_defaults(self) -> None:
        """Apply sensible default mappings when profile is empty."""
        try:
            prof = self._current_profile()
        except Exception:
            return

        mappings = prof.get("mappings", {})
        if isinstance(mappings, dict) and mappings:
            # Profile already has mappings, don't overwrite
            return

        hs = self._keymap_hotspots()
        if not hs:
            return

        defaults: Dict[str, Tuple[int, int]] = {
            "D-UP": (0, 0x1A),  # W
            "D-DN": (0, 0x16),  # S
            "D-L": (0, 0x04),  # A
            "D-R": (0, 0x07),  # D
            "A": (0, 0x2C),  # Space
            "B": (0, 0x08),  # E
            "X": (0, 0x15),  # R
            "Y": (0, 0x19),  # V
            "ZL": (0x02, 0),  # LShift
            "ZR": (0x01, 0),  # LCtrl
        }

        mappings = prof.setdefault("mappings", {})
        if not isinstance(mappings, dict):
            mappings = {}
            prof["mappings"] = mappings

        applied = 0
        for name, (mod, kc) in defaults.items():
            key_id = hs.get(name)
            if key_id is not None and str(key_id) not in mappings:
                mappings[str(key_id)] = {"type": "remap_hid", "mod": mod, "keycode": kc}
                applied += 1

        if applied > 0:
            self._set_profile_obj(prof, undo_label="smart defaults")
            self._log_line(f"[host] Smart defaults applied: {applied} mappings")

    # ------------------------------------------------------------------
    # Lock Critical Inputs
    # ------------------------------------------------------------------

    def _is_locked(self, hotspot: str) -> bool:
        return hotspot in self._locked_hotspots

    def _check_lock_before_unbind(self, hotspot: str, action: str) -> bool:
        """Return True if the action is allowed. Shows confirmation for locked hotspots."""
        if hotspot not in self._locked_hotspots:
            return True
        return messagebox.askyesno(
            "Locked Input",
            f"'{hotspot}' is marked as a critical input.\n\n"
            f"Are you sure you want to {action}?",
        )

    # ------------------------------------------------------------------
    # Debug Chain View ("Why isn't this working?")
    # ------------------------------------------------------------------

    def _explain_mapping(self, hotspot: str) -> str:
        """Build a human-readable explanation of the full mapping chain for a hotspot."""
        hs = self._keymap_hotspots()
        key_id = hs.get(hotspot)

        lines: List[str] = [f"=== {hotspot} Mapping Chain ===", ""]

        if key_id is None:
            lines.append(f"1. Input: {hotspot} — NO key_id learned")
            lines.append("   Status: Not configured. Use Learn to assign a controller button.")
            return "\n".join(lines)

        lines.append(f"1. Input: {hotspot} → key_id = {key_id}")

        # Check if active
        if key_id in self._active_key_ids:
            lines.append("   Status: ACTIVE (button is held down)")
        else:
            lines.append("   Status: idle")

        # Check mapping
        try:
            prof = self._current_profile()
        except Exception:
            lines.append("2. Mapping: ERROR — could not read profile")
            return "\n".join(lines)

        mappings = prof.get("mappings", {})
        entry = mappings.get(str(key_id)) if isinstance(mappings, dict) else None

        if entry is None or not isinstance(entry, dict):
            lines.append("2. Mapping: passthrough (default keymap.c)")
            dk = hid_keycodes.DEFAULT_KEYMAP.get(key_id)
            if dk:
                lines.append(f"3. Output: {hid_keycodes.hid_to_name(dk[0], dk[1])}")
                lines.append("   Status: OK — key will be sent via default mapping")
            else:
                lines.append(f"3. Output: NONE (key_id {key_id} not in default keymap)")
                lines.append("   Status: WARNING — this key_id has no default output")
        else:
            et = entry.get("type", "?")
            lines.append(f"2. Mapping: {et}")

            if et == "disable":
                lines.append("3. Output: DISABLED — input is ignored")
                lines.append("   Status: Intentionally disabled")
            elif et == "remap_hid":
                mod = entry.get("mod", 0)
                kc = entry.get("keycode", 0)
                lines.append(f"3. Output: {hid_keycodes.hid_to_name(mod, kc)} (mod=0x{mod:02X} keycode=0x{kc:02X})")
                lines.append("   Status: OK — direct HID output")
            elif et == "remap":
                to = entry.get("to", 0)
                dk = hid_keycodes.DEFAULT_KEYMAP.get(to)
                if dk:
                    lines.append(f"3. Output: remap to key_id={to} → {hid_keycodes.hid_to_name(dk[0], dk[1])}")
                else:
                    lines.append(f"3. Output: remap to key_id={to} → NOT IN KEYMAP")
                    lines.append("   Status: WARNING — remap target not in default keymap")
            elif et == "macro":
                mid = entry.get("id", "?")
                lines.append(f"3. Output: triggers macro '{mid}'")
                macros = prof.get("macros", [])
                found = any(m.get("id") == mid for m in macros if isinstance(m, dict))
                if found:
                    lines.append("   Status: OK — macro exists in profile")
                else:
                    lines.append(f"   Status: ERROR — macro '{mid}' not found in profile!")
            elif et == "tap_hold":
                tap = entry.get("tap", {})
                hold = entry.get("hold", {})
                hold_ms = entry.get("hold_ms", 300)
                lines.append(f"3. Output (tap <{hold_ms}ms): {tap.get('type', '?')}")
                if isinstance(hold, dict) and hold.get("type") == "remap_hid":
                    hkc = hold.get("keycode", 0)
                    hmod = hold.get("mod", 0)
                    lines.append(f"   Output (hold >={hold_ms}ms): {hid_keycodes.hid_to_name(hmod, hkc)}")
                lines.append("   Status: OK — dual-action mapping")

        # Check for conflicts
        conflicts = self._detect_conflicts()
        for output_key, names in conflicts.items():
            if hotspot in names:
                others = [n for n in names if n != hotspot]
                lines.append(f"")
                lines.append(f"⚠ CONFLICT: Same output '{output_key}' shared with: {', '.join(others)}")

        # Check layer overrides
        layers = prof.get("layers", [])
        if isinstance(layers, list):
            for i, layer in enumerate(layers):
                if isinstance(layer, dict):
                    lm = layer.get("mappings", {})
                    if isinstance(lm, dict) and str(key_id) in lm:
                        lname = layer.get("name", f"Layer {i+1}")
                        lines.append(f"")
                        lines.append(f"Layer override: '{lname}' overrides this key_id")

        return "\n".join(lines)

    def _show_explain_dialog(self, hotspot: str) -> None:
        """Show the mapping explanation in a dialog."""
        text = self._explain_mapping(hotspot)
        win = tk.Toplevel(self)
        win.title(f"Mapping Details — {hotspot}")
        win.geometry("500x350")
        win.attributes("-topmost", True)
        colors = self._colors
        win.configure(bg=colors["bg"])

        txt = ScrolledText(win, height=18, wrap="word")
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self._theme_scrolled_text(txt)
        txt.insert("1.0", text)
        txt.configure(state="disabled")

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 8))

    # ── Feedback sounds ──
    _sounds_enabled: bool = True

    def _play_sound(self, kind: str = "bind") -> None:
        """Play a short feedback sound (non-blocking). kind: bind, unbind, error, undo."""
        if not _HAS_WINSOUND or not self._sounds_enabled:
            return
        freq_map = {"bind": (800, 60), "unbind": (400, 60), "error": (300, 120), "undo": (600, 50)}
        freq, dur = freq_map.get(kind, (600, 60))
        threading.Thread(target=winsound.Beep, args=(freq, dur), daemon=True).start()

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
        self._play_sound("bind")

        # Auto-advance: select the next unbound hotspot for fast sequential mapping.
        if self._guided_window is None:
            self._auto_advance_to_next_unbound(learned_name)

    def _auto_advance_to_next_unbound(self, current_name: str) -> None:
        """Select the next unbound hotspot in the KEYMAP_HOTSPOTS order."""
        hs = self._keymap_hotspots()
        names = [n for n, _x, _y in KEYMAP_HOTSPOTS]
        try:
            idx = names.index(current_name)
        except ValueError:
            return
        # Scan forward from current+1, wrapping around
        for offset in range(1, len(names)):
            candidate = names[(idx + offset) % len(names)]
            if candidate not in hs:
                self._keymap_selected_name = candidate
                self._keymap_status.set(
                    f"Auto-selected '{candidate}' — press Learn to bind, or click another."
                )
                self._keymap_dirty = True
                return

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
            log.info("Disconnecting serial")
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

        log.info("Connecting to %s @ %d", port, baud)
        try:
            self.client.connect(port, baud)
        except Exception as e:
            log.error("Serial connect failed: %s", e, exc_info=True)
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

    def _set_profile_obj(self, obj: dict, undo_label: str = "edit") -> None:
        # Push current state to undo stack before overwriting
        if not self._suppress_undo:
            try:
                old_raw = self.profile_text.get("1.0", "end").strip()
                if old_raw:
                    self._undo_stack.append((undo_label, old_raw))
                    if len(self._undo_stack) > self._undo_max:
                        self._undo_stack = self._undo_stack[-self._undo_max:]
                    self._redo_stack.clear()
            except Exception:
                pass
            self._update_undo_ui()

        obj = _ensure_profile_defaults(obj)
        self.profile_text.delete("1.0", "end")
        self.profile_text.insert("1.0", json.dumps(obj, indent=2, ensure_ascii=False))
        self._invalidate_caches()
        self._refresh_macro_list()
        self._stick_load_from_profile(obj)
        self._keymap_refresh_visuals()

    def _load_profile(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All files", "*")])
        if not path:
            return
        log.info("Loading profile from %s", path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
        except Exception as e:
            log.error("Profile load failed: %s", e, exc_info=True)
            messagebox.showerror("Load failed", str(e))
            return
        self.profile_text.delete("1.0", "end")
        self.profile_text.insert("1.0", data)
        try:
            prof = self._validate_profile()
            self._refresh_macro_list()
            self._stick_load_from_profile(prof)
        except Exception:
            log.warning("Loaded profile failed validation", exc_info=True)

    def _save_profile(self) -> None:
        try:
            self._validate_profile()
        except Exception:
            return

        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        log.info("Saving profile to %s", path)
        data = self.profile_text.get("1.0", "end").strip() + "\n"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(data)
        except Exception as e:
            log.error("Profile save failed: %s", e, exc_info=True)
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
        log.debug("TX cmd: %s", obj)
        try:
            self.client.send_obj(obj)
        except Exception as e:
            log.error("Send cmd failed: %s", e, exc_info=True)
            messagebox.showerror("Send failed", str(e))
            return
        self._log_line(f"[host->dev] {json.dumps(obj, ensure_ascii=False)}")

    def _send_text(self, text: str) -> None:
        log.debug("TX text: %s", text)
        try:
            self.client.send_text_line(text)
        except Exception as e:
            log.error("Send text failed: %s", e, exc_info=True)
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
        except Exception as exc:
            # queue.Empty is expected when the queue is drained; only log real errors.
            import queue as _q
            if not isinstance(exc, _q.Empty):
                log.warning("Unexpected error in _drain_rx: %s", exc, exc_info=True)
        self.after(50, self._drain_rx)

    def _handle_dev_obj(self, obj: dict) -> None:
        evt = obj.get("evt")

        # Handle command responses (rsp)
        rsp = obj.get("rsp")
        if rsp == "read_profile":
            slot = obj.get("slot")
            profile = obj.get("profile")
            if isinstance(slot, int) and isinstance(profile, dict):
                name = profile.get("name", f"(slot {slot})")
                self._slot_update_name(slot, str(name))
                # If this is the actively selected slot, load the profile into the editor
                try:
                    if int(self.slot_var.get()) == slot:
                        self._set_profile_obj(_ensure_profile_defaults(profile))
                        self._profile_name_var.set(str(name))
                except Exception:
                    pass
            elif isinstance(slot, int):
                self._slot_update_name(slot, "(empty)")

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

            # Guided wizard captures input before normal learn flow.
            if pressed and self._guided_window is not None:
                self._guided_on_input(key_id)

            # Keymap editor learn mode: bind hotspot -> observed input key_id.
            if pressed and self._keymap_learn_name:
                self._keymap_bind_selected(key_id)

            # Live input visualization: track active keys for hotspot highlighting.
            if pressed:
                self._active_key_ids.add(key_id)
            else:
                self._active_key_ids.discard(key_id)
            self._keymap_dirty = True  # Batched: redrawn on next pulse tick (≤80ms)

            # Input test tab: log the event and update active display.
            try:
                recv_t = time.monotonic()
                ts = time.strftime("%H:%M:%S")
                action = "pressed" if pressed else "released"
                # Use cached reverse lookup
                name = self._get_hotspot_name(key_id)
                self._input_test_append(f"[{ts}] {name} {action}")

                # Add to visual timeline
                tl_color = self._colors.get("accent2", "#3a8a5c") if pressed else self._colors.get("muted", "#888")
                self._timeline_add_event(name, tl_color)

                if self._active_key_ids:
                    names = [self._get_hotspot_name(kid) for kid in sorted(self._active_key_ids)]
                    self._input_test_active_var.set(", ".join(names))
                else:
                    self._input_test_active_var.set("(none)")

                # Record latency for profiling
                if self._perf_enabled:
                    self._perf_input_times.append((recv_t, time.monotonic()))
                    if len(self._perf_input_times) > 100:
                        self._perf_input_times = self._perf_input_times[-100:]
            except Exception:
                pass

        if evt == "layer":
            # Layer state change from firmware.
            name = obj.get("name", "?")
            active = obj.get("active", False)
            ts = time.strftime("%H:%M:%S")
            state_str = "activated" if active else "deactivated"
            self._log_line(f"[device] Layer '{name}' {state_str}")
            try:
                self._input_test_append(f"[{ts}] Layer '{name}' {state_str}")
            except Exception:
                pass

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

                # Auto-apply smart defaults if profile is mostly empty.
                self.after(500, self._apply_smart_defaults)

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
        if not hasattr(self, "macro_list"):
            return
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
        if not hasattr(self, "macro_list"):
            return None
        sel = self.macro_list.curselection()
        if not sel:
            return None
        return int(sel[0])

    def _refresh_macro_steps(self) -> None:
        if not hasattr(self, "step_list"):
            return
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
        elif mtype == "remap_hid":
            # Use the Remap-to field as the HID keycode (hex or int)
            rto = self._mapping_remap_to.get().strip()
            try:
                kc = int(rto, 0)  # Accept hex (0x1A) or decimal
            except ValueError:
                messagebox.showerror("Bad keycode", "Remap-to must be a HID keycode (integer or 0xHH)")
                return
            if kc < 0 or kc > 255:
                messagebox.showerror("Bad keycode", "HID keycode must be 0..255")
                return
            mappings[key] = {"type": "remap_hid", "mod": 0, "keycode": kc}
        elif mtype == "tap_hold":
            # Tap → passthrough (quick press), Hold → remap_hid (long press)
            rto = self._mapping_remap_to.get().strip()
            try:
                kc = int(rto, 0)
            except ValueError:
                messagebox.showerror("Bad keycode", "Remap-to (hold action) must be a HID keycode")
                return
            if kc < 0 or kc > 255:
                messagebox.showerror("Bad keycode", "HID keycode must be 0..255")
                return
            hold_ms = 300  # default threshold
            mappings[key] = {
                "type": "tap_hold",
                "tap": {"type": "passthrough"},
                "hold": {"type": "remap_hid", "mod": 0, "keycode": kc},
                "hold_ms": hold_ms,
            }

        self._set_profile_obj(prof, undo_label="apply mapping")
        self._keymap_redraw()
        self._rebuild_layer_stack()
        self._play_sound("bind")

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

    def _start_update_check(self) -> None:
        """Kick off a background update check."""
        def _on_result(info: Optional[Dict[str, Any]]) -> None:
            # Called from a background thread → schedule onto the Tk main loop.
            self.after(0, self._on_update_result, info)

        updater.check_in_background(_on_result)

    def _on_update_result(self, info: Optional[Dict[str, Any]]) -> None:
        if info is None:
            return
        self._pending_update = info
        # Show the update icon in the top bar.
        self._update_icon_btn.configure(text=f" \u2191 Update to {info['version']} ")
        self._update_icon_btn.pack(side=tk.LEFT, padx=(12, 0))
        log.info("Update available: %s \u2192 %s", __version__, info["version"])

    # ------------------------------------------------------------------
    # Update dialog — download, install, relaunch
    # ------------------------------------------------------------------

    def _open_update_dialog(self) -> None:
        """Open a modal dialog to download and install the update."""
        info = self._pending_update
        if not info:
            return

        if not updater.is_frozen():
            import webbrowser
            url = info.get("html_url", "")
            if url:
                webbrowser.open(url)
            return

        dlg = tk.Toplevel(self)
        dlg.title("Update Bind Bandit")
        dlg.geometry("440x280")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 440) // 2
        y = self.winfo_y() + (self.winfo_height() - 280) // 2
        dlg.geometry(f"+{x}+{y}")

        pad = ttk.Frame(dlg, padding=16)
        pad.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            pad, text="Update Available",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            pad, text=f"v{__version__}  \u2192  v{info['version']}",
        ).pack(anchor="w", pady=(4, 12))

        step_var = tk.StringVar(value="Ready to update.")
        ttk.Label(pad, textvariable=step_var, wraplength=400).pack(
            anchor="w", pady=(0, 4),
        )

        progress = ttk.Progressbar(pad, length=400, mode="determinate")
        progress.pack(fill=tk.X, pady=(0, 4))

        detail_var = tk.StringVar(value="")
        ttk.Label(pad, textvariable=detail_var, style="Muted.TLabel").pack(anchor="w")

        btn_frame = ttk.Frame(pad)
        btn_frame.pack(fill=tk.X, pady=(12, 0))

        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=dlg.destroy)
        cancel_btn.pack(side=tk.RIGHT, padx=(8, 0))

        install_btn = ttk.Button(
            btn_frame, text="Download & Install",
            command=lambda: self._run_update_flow(
                dlg, info, step_var, progress, detail_var,
                install_btn, cancel_btn,
            ),
        )
        install_btn.pack(side=tk.RIGHT)

        dlg._updating = False  # type: ignore[attr-defined]

        def _on_close() -> None:
            if getattr(dlg, "_updating", False):
                return
            dlg.destroy()

        dlg.protocol("WM_DELETE_WINDOW", _on_close)

    def _run_update_flow(
        self,
        dlg: tk.Toplevel,
        info: Dict[str, Any],
        step_var: tk.StringVar,
        progress: ttk.Progressbar,
        detail_var: tk.StringVar,
        install_btn: ttk.Button,
        cancel_btn: ttk.Button,
    ) -> None:
        """Execute the full download \u2192 install \u2192 relaunch pipeline on a thread."""
        dlg._updating = True  # type: ignore[attr-defined]
        install_btn.configure(state="disabled")
        cancel_btn.configure(state="disabled")

        def _set(step: str = "", detail: str = "", pct: int = 0) -> None:
            def _apply() -> None:
                step_var.set(step)
                detail_var.set(detail)
                progress.configure(value=pct)
            self.after(0, _apply)

        def _worker() -> None:
            try:
                # 1. Download app executable
                _set("Downloading app update\u2026", "", 0)

                def _app_cb(dl: int, tot: int) -> None:
                    pct = int(dl * 100 / tot) if tot else 0
                    _set(
                        "Downloading app update\u2026",
                        f"{dl // 1024} / {tot // 1024} KB",
                        pct,
                    )

                exe_bytes = updater.download_bytes(
                    info["download_url"], progress_cb=_app_cb,
                )

                # 2. Download firmware assets (if any in this release)
                fw_assets = info.get("fw_assets", {})
                fw_data: Dict[str, bytes] = {}
                for name, asset_info in fw_assets.items():
                    _set(f"Downloading firmware ({name})\u2026", "", 0)

                    def _fw_cb(dl: int, tot: int, n: str = name) -> None:
                        pct = int(dl * 100 / tot) if tot else 0
                        _set(
                            f"Downloading firmware ({n})\u2026",
                            f"{dl // 1024} / {tot // 1024} KB",
                            pct,
                        )

                    fw_data[name] = updater.download_bytes(
                        asset_info["url"], progress_cb=_fw_cb,
                    )

                # 3. Save firmware for post-relaunch flashing
                if fw_data:
                    _set("Saving firmware\u2026", "", 0)
                    for fname, fdata in fw_data.items():
                        updater.save_pending_firmware(fname, fdata)

                # 4. Install new exe
                _set("Installing update\u2026", "Swapping executable\u2026", 50)
                updater.install_exe(exe_bytes)
                _set("Installing update\u2026", "Done!", 100)

                # 5. Relaunch
                _set("Restarting\u2026", "The app will relaunch now.", 100)
                self.after(1200, updater.relaunch)

            except Exception as e:
                log.error("Update flow failed: %s", e, exc_info=True)
                self.after(0, lambda: self._on_update_flow_error(
                    dlg, str(e), install_btn, cancel_btn,
                ))

        threading.Thread(target=_worker, name="update-flow", daemon=True).start()

    def _on_update_flow_error(
        self,
        dlg: tk.Toplevel,
        error: str,
        install_btn: ttk.Button,
        cancel_btn: ttk.Button,
    ) -> None:
        dlg._updating = False  # type: ignore[attr-defined]
        install_btn.configure(state="normal")
        cancel_btn.configure(state="normal", text="Close")
        messagebox.showerror("Update failed", error, parent=dlg)

    # ------------------------------------------------------------------
    # Pending firmware flash (runs after a successful app update + relaunch)
    # ------------------------------------------------------------------

    def _check_pending_fw(self) -> None:
        """Periodically check whether we should offer to flash pending firmware."""
        if not self._pending_fw_files:
            return
        if not self.serial.is_connected:
            # Not connected yet — retry later.
            self.after(5000, self._check_pending_fw)
            return
        if self._pending_fw_offered:
            return
        self._pending_fw_offered = True
        self.after(500, self._offer_pending_fw_flash)

    def _offer_pending_fw_flash(self) -> None:
        files = self._pending_fw_files
        board_names: List[str] = []
        if updater.FW_ASSET_S3 in files:
            board_names.append("ESP32-S3")
        if updater.FW_ASSET_ESP32 in files:
            board_names.append("ESP32")

        if not board_names:
            updater.clear_pending_firmware()
            self._pending_fw_files = {}
            return

        confirm = messagebox.askyesno(
            "Firmware Update Ready",
            f"Updated firmware is ready for: {', '.join(board_names)}.\n\n"
            "Flash now?\n\n"
            "Do not disconnect during the update.",
        )
        if not confirm:
            updater.clear_pending_firmware()
            self._pending_fw_files = {}
            return

        self._flash_pending_fw()

    def _flash_pending_fw(self) -> None:
        """Flash saved firmware binaries with a progress dialog."""
        dlg = tk.Toplevel(self)
        dlg.title("Flashing Firmware")
        dlg.geometry("440x200")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 440) // 2
        y = self.winfo_y() + (self.winfo_height() - 200) // 2
        dlg.geometry(f"+{x}+{y}")

        pad = ttk.Frame(dlg, padding=16)
        pad.pack(fill=tk.BOTH, expand=True)

        step_var = tk.StringVar(value="Preparing\u2026")
        ttk.Label(
            pad, textvariable=step_var,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")

        progress = ttk.Progressbar(pad, length=400, mode="determinate")
        progress.pack(fill=tk.X, pady=(8, 4))

        detail_var = tk.StringVar(value="")
        ttk.Label(pad, textvariable=detail_var, style="Muted.TLabel").pack(anchor="w")

        dlg.protocol("WM_DELETE_WINDOW", lambda: None)

        def _set(step: str = "", detail: str = "", pct: int = 0) -> None:
            def _apply() -> None:
                step_var.set(step)
                detail_var.set(detail)
                progress.configure(value=pct)
            self.after(0, _apply)

        files = self._pending_fw_files
        boards_to_flash: List[Tuple[str, Path]] = []
        if updater.FW_ASSET_S3 in files:
            boards_to_flash.append((fw_updater.BOARD_S3, files[updater.FW_ASSET_S3]))
        if updater.FW_ASSET_ESP32 in files:
            boards_to_flash.append((fw_updater.BOARD_ESP32, files[updater.FW_ASSET_ESP32]))

        def _worker() -> None:
            try:
                flasher = fw_updater.FirmwareFlasher(self.serial)
                for board, fw_path in boards_to_flash:
                    _set(f"Flashing {board}\u2026", "Reading firmware\u2026", 0)
                    fw_bytes = fw_path.read_bytes()

                    def _progress(done: int, total: int, b: str = board) -> None:
                        pct = int(done * 100 / total) if total else 0
                        _set(
                            f"Flashing {b}\u2026",
                            f"{done // 1024} / {total // 1024} KB",
                            pct,
                        )

                    flasher.flash(board, fw_bytes, progress_cb=_progress)

                _set("Firmware update complete!", "Device will reboot.", 100)
                updater.clear_pending_firmware()
                self._pending_fw_files = {}
                self.after(2000, dlg.destroy)
                self.after(2100, lambda: messagebox.showinfo(
                    "Firmware Updated",
                    "Firmware has been updated successfully.\n"
                    "The device will reboot. You may need to reconnect.",
                ))
            except Exception as e:
                log.error("Pending FW flash failed: %s", e, exc_info=True)
                _set(f"Error: {e}", "", 0)
                updater.clear_pending_firmware()
                self._pending_fw_files = {}
                self.after(3000, dlg.destroy)
                self.after(3100, lambda: messagebox.showerror(
                    "Firmware Flash Failed", str(e),
                ))

        threading.Thread(target=_worker, name="pending-fw-flash", daemon=True).start()

    # ------------------------------------------------------------------
    # Firmware version check & OTA update
    # ------------------------------------------------------------------

    def _fw_check_versions(self) -> None:
        """Query firmware versions from both boards over serial."""
        if not self.serial.is_connected:
            self._fw_status.set("Not connected.")
            return

        self._fw_check_btn.configure(state="disabled")
        self._fw_status.set("Querying…")

        def _worker() -> None:
            flasher = fw_updater.FirmwareFlasher(self.serial)
            s3_ver = flasher.get_version(fw_updater.BOARD_S3)
            esp32_ver = flasher.get_version(fw_updater.BOARD_ESP32)
            self.after(0, lambda: self._on_fw_versions(s3_ver, esp32_ver))

        import threading
        threading.Thread(target=_worker, name="fw-version-check", daemon=True).start()

    def _on_fw_versions(self, s3_ver: Optional[str], esp32_ver: Optional[str]) -> None:
        self._fw_check_btn.configure(state="normal")
        self._fw_s3_ver.set(f"S3: {s3_ver or '—'}")
        self._fw_esp32_ver.set(f"ESP32: {esp32_ver or '—'}")

        if not s3_ver and not esp32_ver:
            self._fw_status.set("Could not read versions.")
            return

        # Check for updates against GitHub Releases.
        self._fw_status.set("Checking for updates…")

        def _check() -> None:
            info = fw_updater.check_firmware_updates(
                current_s3=s3_ver, current_esp32=esp32_ver
            )
            self.after(0, lambda: self._on_fw_update_check(info))

        import threading
        threading.Thread(target=_check, name="fw-update-check", daemon=True).start()

    def _on_fw_update_check(self, info: Optional[Dict[str, Any]]) -> None:
        if info is None or not info.get("boards"):
            self._fw_status.set("Firmware up to date.")
            self._fw_update_btn.configure(state="disabled")
            self._pending_fw_update = None
            return

        boards = info["boards"]
        parts = []
        if fw_updater.BOARD_S3 in boards:
            parts.append("S3")
        if fw_updater.BOARD_ESP32 in boards:
            parts.append("ESP32")
        self._fw_status.set(f"Update available for: {', '.join(parts)} → {info['version']}")
        self._fw_update_btn.configure(state="normal")
        self._pending_fw_update = info

    def _fw_do_update(self) -> None:
        info = self._pending_fw_update
        if not info or not self.serial.is_connected:
            return

        boards = info.get("boards", {})
        board_names = [b for b in [fw_updater.BOARD_S3, fw_updater.BOARD_ESP32] if b in boards]
        if not board_names:
            return

        confirm = messagebox.askyesno(
            "Firmware update",
            f"Update firmware for {', '.join(board_names)} to v{info['version']}?\n\n"
            "The device(s) will reboot after flashing.\n"
            "Do not disconnect during the update.",
        )
        if not confirm:
            return

        self._fw_update_btn.configure(state="disabled")
        self._fw_check_btn.configure(state="disabled")
        self._fw_status.set("Downloading…")

        def _run() -> None:
            try:
                flasher = fw_updater.FirmwareFlasher(self.serial)
                for board in board_names:
                    b_info = boards[board]
                    self.after(0, lambda b=board: self._fw_status.set(f"Downloading {b}…"))

                    fw_bytes = fw_updater.download_firmware(
                        b_info["download_url"],
                        progress_cb=lambda dl, tot, b=board: self.after(
                            0, lambda: self._fw_status.set(
                                f"Downloading {b}… {int(dl * 100 / tot)}%"
                            )
                        ),
                    )

                    self.after(0, lambda b=board: self._fw_status.set(f"Flashing {b}…"))

                    flasher.flash(
                        board, fw_bytes,
                        progress_cb=lambda done, tot, b=board: self.after(
                            0, lambda: self._fw_status.set(
                                f"Flashing {b}… {int(done * 100 / tot)}%"
                            )
                        ),
                    )

                self.after(0, self._on_fw_update_done)
            except Exception as e:
                log.error("Firmware update failed: %s", e, exc_info=True)
                self.after(0, lambda: self._on_fw_update_failed(str(e)))

        import threading
        threading.Thread(target=_run, name="fw-update", daemon=True).start()

    def _on_fw_update_done(self) -> None:
        self._fw_check_btn.configure(state="normal")
        self._fw_status.set("Firmware updated! Device rebooting…")
        self._pending_fw_update = None
        messagebox.showinfo(
            "Firmware updated",
            "Firmware has been updated successfully.\n\n"
            "The device will reboot. You may need to reconnect.",
        )

    def _on_fw_update_failed(self, error: str) -> None:
        self._fw_check_btn.configure(state="normal")
        self._fw_update_btn.configure(state="normal")
        self._fw_status.set(f"Update failed: {error}")
        messagebox.showerror("Firmware update failed", error)

    def _log_line(self, text: str) -> None:
        log.debug("SERIAL: %s", text)
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> None:
    log.info("Starting Bind Bandit")
    try:
        app = App()
    except Exception as e:
        log.critical("Startup failed: %s", e, exc_info=True)
        messagebox.showerror("Startup failed", str(e))
        raise
    log.info("UI mainloop starting")
    try:
        app.mainloop()
    finally:
        log.info("Application exiting")
