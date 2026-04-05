"""Tkinter layout snippet (matches current helper app structure).

This is a *reference snippet* for UI planning.
It is not imported by the helper app.

Structure:
- Top bar: port + baud + connect
- Main body: tabs + right-side actions
- Bottom: log view
"""

import tkinter as tk
import tkinter.ttk as ttk
from tkinter.scrolledtext import ScrolledText


def build_ui(root: tk.Tk) -> None:
    root.title("JoyCon Bridge Helper")
    root.geometry("980x680")

    top = tk.Frame(root)
    top.pack(fill=tk.X, padx=8, pady=8)

    tk.Label(top, text="Port:").pack(side=tk.LEFT)
    port_var = tk.StringVar(value="")
    tk.OptionMenu(top, port_var, "").config(width=40)

    tk.Label(top, text="Baud:").pack(side=tk.LEFT, padx=(12, 0))
    baud_var = tk.StringVar(value="115200")
    tk.Entry(top, textvariable=baud_var, width=10).pack(side=tk.LEFT, padx=(4, 8))

    tk.Button(top, text="Connect").pack(side=tk.LEFT)

    body = tk.Frame(root)
    body.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    left = tk.Frame(body)
    left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    right = tk.Frame(body)
    right.pack(side=tk.RIGHT, fill=tk.Y)

    tabs = ttk.Notebook(left)
    tabs.pack(fill=tk.BOTH, expand=True)

    for name in ["Profile", "Macros", "Stick", "Share", "Overlay", "Controller"]:
        frame = tk.Frame(tabs)
        tabs.add(frame, text=name)

    tk.Label(left, text="Device log / events").pack(anchor="w", pady=(6, 0))
    log = ScrolledText(left, height=14, state="disabled")
    log.pack(fill=tk.BOTH, expand=False)

    tk.Label(right, text="Actions").pack(anchor="w")
    tk.Button(right, text="Upload + Activate", width=22).pack(pady=(8, 0))
    tk.Label(right, text="Raw command (JSON line)").pack(anchor="w", pady=(14, 0))


if __name__ == "__main__":
    r = tk.Tk()
    build_ui(r)
    r.mainloop()
