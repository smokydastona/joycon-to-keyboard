"""Theme-matched ttk styling snippet.

This is a *reference snippet* showing how to apply `theme.json` tokens to ttk.
It is not imported by the helper app.

Tkinter/ttk limitations to keep in mind:
- Many widgets are OS-themed; exact colors vary by platform/theme.
- ttk does not natively support rounded corners; use padding + flat relief.
- A consistent look is still achievable by styling the key controls.

Sketch / sketchbook-ink visual direction (torn parchment):
- font_family is "Segoe Print" (hand-drawn look, ships with Windows).
  Tkinter resolves to the system fallback font if Segoe Print is unavailable —
  safe to always request it.
- Background is a torn parchment sheet sitting on a dark desk surface.
  Panel / widget colors are warm aged-paper tones (bg #e8d8b8, panel #f2e8d0
  panel2 #e2d0a8). The SVG background uses feTurbulence displacement at high
  scale to create ragged torn-paper edges around the parchment.
- Border / outline color is a golden brown ink tone (#b09878) matching the
  sepia ink strokes on the parchment. Text is dark sepia (#2a1f0e).
- Use the 'rough' displacement filter in SVG assets for hand-drawn outlines;
  keep ttk widgets flat (relief="flat") so they sit naturally on the parchment.
- Tea/coffee stain gradients and heavy paper-grain noise add age character.

Dark mode (sketchbook-ink-dark):
- Dark blue ballpoint pen aesthetic — cool blue-grey tones instead of warm sepia.
- Background is very dark blue-black (#10141c), panels are deep blue-grey
  (#181e2c, #202838). Text is light blue-grey (#a8bcd0).
- Accent/success/warning/danger colors are cooler-toned for the blue palette
  (accent #4a7cc8, danger #c84848, etc.).
- The dark bundle is generated alongside the light bundle: .ui-bundle-dark/.
- The helper app auto-detects Windows dark mode via the registry
  (AppsUseLightTheme = 0), or accepts JOYCON_THEME=dark env var / --dark flag.
- Both themes share identical typography, spacing, and radii.
"""

from __future__ import annotations

import json
import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path


def load_theme(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def apply_theme(root: tk.Tk, theme: dict) -> None:
    colors = theme["colors"]
    typo = theme["typography"]

    root.configure(bg=colors["bg"])

    style = ttk.Style(root)

    # Pick a base theme that is predictable on Windows.
    # 'vista' is common; fallback gracefully.
    try:
        style.theme_use("vista")
    except Exception:
        pass

    style.configure(
        "TFrame",
        background=colors["bg"],
    )

    style.configure(
        "Card.TFrame",
        background=colors["panel"],
        bordercolor=colors["border"],
        relief="flat",
    )

    style.configure(
        "TLabel",
        background=colors["bg"],
        foreground=colors["text"],
        font=(typo["font_family"], int(typo["font_size"])),
    )

    style.configure(
        "Muted.TLabel",
        background=colors["bg"],
        foreground=colors["muted"],
    )

    # Buttons
    style.configure(
        "TButton",
        padding=(10, 6),
    )

    style.configure(
        "Primary.TButton",
        padding=(10, 6),
    )

    # Note: true background color for ttk buttons is platform/theme-dependent.
    # If you need strict colors, switch key buttons to `tk.Button` and use these tokens.

    # Checkbuttons / toggles
    style.configure("TCheckbutton", background=colors["bg"], foreground=colors["text"])

    # Scales (dials/slider feel)
    style.configure("TScale", background=colors["bg"])


def demo() -> None:
    theme = load_theme("./.ui-bundle/theme.json")

    root = tk.Tk()
    root.title("Theme demo")
    root.geometry("720x320")

    apply_theme(root, theme)

    outer = ttk.Frame(root, padding=16)
    outer.pack(fill=tk.BOTH, expand=True)

    title = ttk.Label(outer, text="Theme demo")
    title.pack(anchor="w")

    ttk.Label(outer, text="Muted label", style="Muted.TLabel").pack(anchor="w", pady=(4, 12))

    row = ttk.Frame(outer)
    row.pack(anchor="w", pady=(0, 12))

    ttk.Button(row, text="Secondary").pack(side="left")
    ttk.Button(row, text="Primary", style="Primary.TButton").pack(side="left", padx=(8, 0))

    v = tk.BooleanVar(value=True)
    ttk.Checkbutton(outer, text="Toggle", variable=v).pack(anchor="w", pady=(0, 12))

    s = tk.DoubleVar(value=0.15)
    ttk.Scale(outer, from_=0.0, to=0.5, variable=s, orient="horizontal", length=320).pack(anchor="w")

    root.mainloop()


if __name__ == "__main__":
    demo()
