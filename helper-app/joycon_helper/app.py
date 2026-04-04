from __future__ import annotations

import json
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

from serial.tools import list_ports

from .serial_client import SerialClient


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("JoyCon Bridge Helper")
        self.geometry("980x680")

        self.client = SerialClient()

        self.port_var = tk.StringVar(value="")
        self.baud_var = tk.StringVar(value="115200")
        self.slot_var = tk.StringVar(value="0")

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

        # Profile editor (JSON)
        tk.Label(left, text="Profile JSON").pack(anchor="w")
        self.profile_text = ScrolledText(left, height=18)
        self.profile_text.pack(fill=tk.BOTH, expand=True)
        self.profile_text.insert("1.0", json.dumps({"name": "default", "mapping": {}}, indent=2))

        prof_btns = tk.Frame(left)
        prof_btns.pack(fill=tk.X, pady=(6, 6))
        tk.Button(prof_btns, text="Load…", command=self._load_profile).pack(side=tk.LEFT)
        tk.Button(prof_btns, text="Save…", command=self._save_profile).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(prof_btns, text="Validate", command=self._validate_profile).pack(side=tk.LEFT, padx=(6, 0))

        # Log view
        tk.Label(left, text="Device log / events").pack(anchor="w")
        self.log = ScrolledText(left, height=14, state="disabled")
        self.log.pack(fill=tk.BOTH, expand=True)

        # Right side controls
        tk.Label(right, text="Actions").pack(anchor="w")

        slot_row = tk.Frame(right)
        slot_row.pack(fill=tk.X, pady=(6, 0))
        tk.Label(slot_row, text="Slot:").pack(side=tk.LEFT)
        tk.OptionMenu(slot_row, self.slot_var, "0", "1", "2", "3").pack(side=tk.LEFT, padx=(6, 0))

        tk.Button(right, text="Ping", command=self._cmd_ping, width=22).pack(pady=(8, 0))
        tk.Button(right, text="Upload profile to slot", command=self._cmd_write_profile, width=22).pack(pady=(6, 0))
        tk.Button(right, text="Read profile from slot", command=self._cmd_read_profile, width=22).pack(pady=(6, 0))
        tk.Button(right, text="Set active slot", command=self._cmd_set_active, width=22).pack(pady=(6, 0))

        tk.Label(right, text="Raw command (JSON line)").pack(anchor="w", pady=(14, 0))
        self.raw_entry = tk.Entry(right, width=30)
        self.raw_entry.pack(pady=(4, 0))
        tk.Button(right, text="Send", command=self._send_raw, width=22).pack(pady=(6, 0))

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
        return obj

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

    def _cmd_set_active(self) -> None:
        self._send_cmd({"cmd": "set_active_profile", "slot": int(self.slot_var.get())})

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
                else:
                    self._log_line(f"[dev] {line.raw}")
        except Exception:
            pass
        self.after(50, self._drain_rx)

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
