# Changelog

All notable changes to this project will be documented in this file.

Note: The helper app UI is now PyQt6; older changelog entries may mention Tkinter.

Format is based on **Keep a Changelog**, and this project aims to follow **Semantic Versioning** once releases/tags start.
Until then, entries are grouped by date.

## Unreleased

### Added

- **Host-assisted ESP32-S3 first install**: The ESP32 host firmware now exposes a `BBI` installer console on its USB-UART port, plus a temporary raw passthrough mode that lets the Web Flasher drive `esptool-js` through the host. First-time flashing is now host-first: flash the ESP32, wire `GPIO21` -> Nano `B1 / GPIO0` and `GPIO22` -> Nano `RESET`, then let the host flash the Nano ESP32-S3 over the existing bridge UART.

- **Bridge UART relocated to GPIO5/6 (Nano D2/D3)**: Moved bridge UART RX/TX from GPIO44/43 (Nano D0/D1) to GPIO5/6 (Nano D2/D3). Root cause: GPIO43/44 are the I/O MUX defaults for UART0; the bootloader briefly initialises UART0 on those pins and the I/O MUX assignment has higher priority than the GPIO matrix routing for UART1, silently blocking all bridge UART reception even after `CONFIG_ESP_CONSOLE_NONE` and `gpio_reset_pin()` were applied. GPIO5/6 have no UART0 association and are fully conflict-free. Updated Kconfig defaults, wiring.md, arduino-nano-esp32-setup.md, firmware-install.md, sdkconfig.defaults, and help tab.

- **UART diagnostic CDC command (`uart_diag`)**: Added a `{"cmd":"uart_diag"}` command to the ESP32-S3 CDC protocol. Reports bridge UART port, baud, configured GPIO pins, RX pin logic level, buffered byte count, and up to 16 sample bytes read with a 100 ms timeout. Used to diagnose why zero UART frames arrive despite correct software configuration.

- **Nintendo 0x30 key emitting enabled**: Enabled `CONFIG_JOYCON_HOST_TRY_NINTENDO_0X30` and `CONFIG_JOYCON_HOST_NINTENDO_0X30_EMIT_KEYS` in `sdkconfig.defaults`. The Joy-Con setup FSM confirms type=1 (Joy-Con L), fw=3.139, and standard 0x30 full-input reports are streaming correctly after four bug-fix iterations. Button presses and stick movements now generate UART key events to the S3.

### Fixed

- **Reconnect failure starts FSM on disconnected device**: When a reconnect attempt fails (e.g. page timeout → `HID OPEN status=6`), the code unconditionally started the setup FSM with the returned handle, causing an infinite loop of `send_data FAILED` errors. Fixed by checking `param->open.status != 0` and scheduling another reconnect attempt (with exponential backoff) instead of starting the FSM.

- **ESP32-S3 bridge UART blocked by console UART0 on GPIO43/44**: On ESP32-S3, the default console UART (UART0) uses GPIO43 (TX) and GPIO44 (RX) via I/O MUX, which has higher priority than the GPIO matrix routing used by bridge UART1 on the same pins. This silently prevented bridge UART reception, making the entire Joy-Con → UART → USB HID pipeline non-functional. Fixed by disabling the console UART (`CONFIG_ESP_CONSOLE_NONE=y` in `sdkconfig.defaults`) and calling `gpio_reset_pin()` on the bridge UART pins before `uart_set_pin()` to ensure the I/O MUX is reset to GPIO function.

- **Discovery timer cascade prevents Joy-Con from being found**: `bt_hid_host_start_discovery()` calls `esp_bt_gap_cancel_discovery()` before starting a new scan, which fires `DISC_STATE_CHANGED(0)`. That state-0 event unconditionally started a 2 s restart timer, which fired mid-scan and cancelled it via the next `cancel_discovery()` call, creating an infinite loop of 2 s scans instead of the configured 10 s. Fixed by stopping the restart timer when a scan actually starts (state=1) and only arming a new timer on state=0 when no timer is already pending.

- **Log flooding kills BT connection after ~2 s of reports**: HID report change detection (`CONFIG_JOYCON_HOST_LOG_REPORTS`) compared bytes that change every frame — originally the full 49-byte report (including IMU), then bytes 0–11 (including the timer byte), then bytes 2–11 (including stick data which changes at 60 Hz during movement). Each iteration still flooded the 115200 baud console, blocking the BTC callback task and triggering the task watchdog. Fixed by: (a) gating the hex dump on only the 3 button bytes (bytes 3–5), and (b) gating the mapper's parsed-state log on button-only changes (stick values are still included in the log line for context but don't trigger output on their own).

- **`vTaskDelay` in GAP callback blocks all BT processing**: Discovery auto-restart used `vTaskDelay(pdMS_TO_TICKS(2000))` inside the BTC callback task, preventing any Bluetooth events from being processed for 2 s. Replaced with a one-shot `esp_timer` that fires the restart asynchronously.

- **QoS call kills connection after ~3 s**: Even deferred to `fsm_ready()`, `esp_bt_gap_set_qos(TPOLL_MIN)` still triggers `ASSERT_WARN(1 8)` in `lc_task.c` and corrupts the BT controller state, killing HID reports ~3 seconds later. Removed the QoS call entirely — the Joy-Con already streams at 60 Hz on the default poll interval, so the call is unnecessary.

- **Discovery never restarts when Joy-Con isn't paired during first scan**: After the initial 10 s inquiry scan ends without finding a device, discovery was not restarted, requiring a manual board reset. Now the scan automatically restarts (with a 2 s cooldown) if no device is connected when discovery ends.

- **Setup FSM times out on reconnect (sniff-mode race)**: When the Joy-Con enters BT sniff mode immediately after connection, the premature `esp_bt_gap_set_qos(TPOLL_MIN)` call in the OPEN handler races with the power-mode negotiation. The `ASSERT_WARN(1 8)` in `lc_task.c` (ROM code) corrupts internal BT controller state, silencing all further HID reports. Fixed by:
  1. **Removed QoS call entirely** — `esp_bt_gap_set_qos()` triggers ROM-level ASSERT_WARN even when deferred; the default poll interval is sufficient for 60 Hz Joy-Con input.
  2. **Post-connection delay** — new `SETUP_CONNECT_DELAY` FSM state waits `JOYCON_HOST_SETUP_CONNECT_DELAY_MS` (default 500 ms) before sending the first subcmd, letting sniff-mode negotiation finish cleanly.
  3. **Retry logic** — each FSM step now retries up to `JOYCON_HOST_SETUP_MAX_RETRIES` (default 2) times on timeout before advancing, instead of immediately skipping to the next step.
  4. **Faster timeout polling** — main loop reduced from 500 ms to 50 ms for quicker retry cycles.
  5. **BT power-mode logging** — `ESP_BT_GAP_MODE_CHG_EVT` is now handled to log active/sniff/hold/park transitions for easier diagnosis.

- **Joy-Con instantly disconnects after connecting (handle=0xFF race)**: When the Joy-Con completes L2CAP before BTA processes `BTA_HhOpen`, the first OPEN callback has handle=0xFF. Previously, the code tried to disconnect and retry, but this killed the L2CAP link that BTA was about to register. Now the 0xFF OPEN is ignored (the link stays alive), and BTA delivers a second OPEN with a valid handle once it catches up. CLOSE events for handle=0xFF are also ignored as phantom events.

- **ESP32 crash on Joy-Con connect (wrong API parameter type)**: `esp_bt_hid_host_send_data()` takes a BDA (Bluetooth Device Address), not a handle. Passing the `uint16_t` handle (0 or 255) was interpreted as a memory address pointer, causing `LoadProhibited` at `EXCVADDR=0x00000000` (handle=0) or `0x000000FC` (handle=0xFF). Fixed `joycon_setup.c` to store and pass the BDA for all `send_data` and rumble calls. Removed failing `esp_bt_hid_host_set_info()` pre-register call (malloc error). Kept handle=0xFF guard as defense-in-depth.

- **Joy-Con setup FSM off-by-one in 0x21 report parsing**: ACK byte was read from `report[12]` (vibrator input report, always 0x00 → false NACK) instead of `report[13]`. Subcmd ID was read from `report[13]` (ACK byte with MSB set, e.g. 0x82) instead of `report[14]`. Reply data started at `report[14]` instead of `report[15]`. This caused every subcmd reply to be misidentified, all data parsing (device info, serial, colors, calibration) to read garbage, and the FSM to only advance via timeouts.

- Capture real controller HID reports and implement evidence-based mapping in the ESP32 host mapper (no guessing report layouts).

### Fixed (System Audit v2)

- **Serial buffer backpressure (A1)**: `serial_client.py` buffer trimming now evicts only the oldest complete lines instead of clearing the entire buffer, preventing loss of in-flight partial frames.
- **HID operations off main thread (A3)**: `devices.py` M913 and Razer HID read/write operations now run on background `QThread` workers, preventing the GUI from freezing during USB communication.
- **Self-updater signature check (A4)**: downloaded `.exe` updates are now verified via Windows Authenticode (`WinVerifyTrust`) before replacing the running binary. Enforcement gated by `REQUIRE_SIGNATURE` flag for unsigned dev builds.
- **Profile auto-save on edit (B1)**: `main_window.py` now auto-uploads the active profile to the device 2 seconds after the last edit (debounced single-shot timer), preventing unsaved changes from being lost on disconnect.
- **Stick calibration mutex (B2)**: `joycon_mapper.c` `s_cal` struct is now protected by a `portMUX_TYPE` spinlock across all reads (`cal_normalize`, `save_calibration`) and writes (`cal_update`, `clear_calibration`), fixing a data race between the BT callback and bridge_ctrl tasks.
- **Macro queue flush on profile switch (B5)**: `profile_runtime.c` `free_profile()` now calls `xQueueReset(s_macro_q)` before any cleanup, preventing the macro task from executing stale requests against freed step arrays (use-after-free).
- **Timeline idle repaint (C1)**: `timeline.py` timer callback now skips `update()` when no events are in the visible window, reducing idle CPU usage from ~10 FPS constant repaint to near-zero.
- **UWP app detection (C3)**: `app_switcher.py` now detects UWP apps (which report as `ApplicationFrameHost.exe`) and falls back to window title matching. Rules can specify a `title` field for substring matching.
- **Overlay position persistence (C5)**: `overlay_window.py` saves the overlay position to QSettings on drag release and restores it on next launch, clamped to the union of all available screen geometries for multi-monitor safety.
- **Toast accessibility (D2)**: `toast.py` now sets `accessibleName` and `accessibleDescription` on each notification widget for screen reader support.

### Added (UX polish — reWASD-inspired improvements)

- **Visual Macro Builder**: dual-mode macro editor — drag-to-reorder step list (key press/release/delay) with inline editing, and a raw JSON toggle for power users.
- **App Auto-Switch Table**: replaced the app switcher list with a 3-column table (Application, Slot combo, Remove button) plus Browse (`.exe` file picker) and Detect App buttons.
- **Enhanced Tray Menu**: right-click tray icon now includes Profiles ► submenu (switch slots 0–3 with radio checks), Toggle Overlay, and Auto-Switch toggle.
- **First-Run Onboarding Wizard**: 5-page QDialog wizard (Welcome → Connect USB → Pair Controller → Test Input → Done) gated by QSettings; re-run from Settings → Developer.
- **Enhanced Overlay**: shows profile name, active layer, and turbo state. Right-click context menu with opacity presets (30/50/70/100%) and compact mode toggle. Double-click toggles compact. Auto-hide timer support.
- **Centralized Settings Dialog**: 4-tab QTabWidget (General, Overlay, Theme, Developer) with opacity slider, auto-hide spinner, baud rate, log level, and onboarding reset.
- **Toast Notifications**: non-blocking slide-in alerts for serial connect/disconnect and quick warnings. Click to dismiss, auto-dismiss after 3.5s, stacks up to 3.
- **Comprehensive Tooltips**: 31 interactive controls across all views now have descriptive tooltips.
- **Help tab updated**: Settings & System Tray section reflects new tabbed dialog, overlay features, onboarding wizard, and toast notifications. Using Bind Bandit section documents visual macro builder and enhanced overlay.

### Added (Mouse — M913 & Razer improvements, pass 3)

- **M913 wireless PID support**: enumerate now detects both wired (PID 0xFA07) and wireless dongle (PID 0xFA08).
- **M913 snipe button**: new "snipe" action (0x9A marker) provides temporary DPI switch while held.
- **M913 extended LED modes**: wave, reactive, random, alternating, and flashing effects added alongside existing off/steady/respiration/rainbow.
- **M913 color picker**: "…" button next to the LED hex entry opens a native color chooser dialog.
- **M913 retry logic**: each HID packet is retried up to 2× with ACK verification and 50 ms backoff.
- **M913 hardware macros**: 15 macro slots (up to 67 key events each) with `MacroSlot` dataclass, `build_macro_packets()`, and visual Macro Builder popup in the UI.
- **M913 INI import/export**: `export_ini()` / `import_ini()` for m913-ctl compatible INI format. Accessible via Export INI / Import INI buttons.
- **M913 DPI bounds clamping**: `clamp_dpi()` snaps arbitrary values to the nearest valid hardware step (100–16000).
- **M913 diagnostics popup**: raw HID packet viewer — send custom hex packets, read reports, and view device info.
- **Razer hypershift layer**: `get_button_function()` and `set_button_function()` accept a `hypershift` parameter for the alternate binding layer.
- **Razer CRC validation**: `_send_report()` verifies XOR checksum (bytes 2–87) and transaction ID on every response.
- **Razer F13–F24 keycodes**: added to `HID_KEYCODES` and `REMAP_ACTIONS` for extended keyboard binding.
- **Razer DPI bounds**: `set_dpi()` now clamps values to the per-model hardware max (e.g., 16000 for Basilisk X, 26000 for V3).
- **F13–F24 in hid_keycodes.py**: added to both `_KEYCODE_NAMES` reverse map and `_KEYSYM_MAP` forward map.
- **Profile versioning (v2)**: both M913Profile and RazerProfile now emit `"ver": 2` with backward-compatible v1 loading.

### Fixed

- **Help tab syntax error**: removed stray double comma in serial protocol section that caused a `SyntaxError` on app startup.
- **BT send mutex (CRITICAL)**: all `esp_bt_hid_host_send_data()` calls in `joycon_setup.c` are now serialised behind a FreeRTOS mutex. Previously the FSM task (`send_subcmd`) and `ctrl_task` (rumble/home-LED) could race on the BT stack, risking corrupted output reports.
- **Sticky modifier leak on profile switch (HIGH)**: `free_profile()` now releases all currently-held sticky keys from the USB HID report before clearing `s_sticky_state[]`. Previously, switching profiles while a sticky modifier was active left a phantom key press in the HID report.
- **Macro delay budget overshoot (HIGH)**: individual macro delay steps are now clamped to the remaining time budget (5 000 ms total, matching JSON validation). A single delay step >5 s no longer blows past the safety cap — it is truncated to whatever time remains.
- **Serial RX thread join (MED)**: `serial_client.py` `disconnect()` now calls `_rx_thread.join(timeout=2.0)` before discarding the reference, preventing a stale thread from lingering after rapid disconnect/reconnect cycles.
- **HID enumerate path guard (MED)**: `m913_device.py` and `razer_device.py` `enumerate()` now use `d.get("path")` and skip entries with no path, preventing `KeyError` on malformed HID descriptors.
- **Stick calibration validation**: `parse_stick_cal()` now validates `min < center < max` after parsing SPI flash data. Corrupt / all-0xFF calibration values are replaced with safe defaults (512 / 2048 / 3584) and a warning is logged.
- **Unknown profile mapping type warning**: `parse_mappings()` now logs `ESP_LOGW` for unrecognised mapping type strings instead of silently ignoring them.
- **tud_hid_set_report_cb documented intent**: the empty stub now has a comment explaining that LED output reports are intentionally ignored (no indicator LEDs on the bridge).
- **app_switcher ctypes crash guard**: `_get_foreground_exe()` and `_get_foreground_title()` are now wrapped in `try/except OSError` so a transient Win32 failure doesn't crash the app-switching poller.
- **Updater .old.exe cleanup log level**: failure to delete the leftover `.old.exe` after a self-update now logs at `WARNING` instead of `DEBUG`, making it visible in default log output.

- **Macro queue overflow guard (H1)**: profile_runtime macro queue increased from 4→8 entries and `xQueueSend` return value is now checked — if the queue is full, a warning is logged instead of silently dropping the macro.
- **OTA chunk retry (H2)**: individual OTA chunks now retry up to 3 times with linear backoff (0.5 s × attempt) before aborting. A single transient USB/serial error no longer kills the entire firmware update.
- **Layout window size mismatch (M4)**: `generate_ui_bundle.py` DEFAULT_LAYOUT window dimensions corrected from 980×720 to 1280×760 to match the actual app geometry.
- **HID write error surfacing (M7)**: `m913_device.py` and `razer_device.py` now catch exceptions from `send_feature_report()` and re-raise as `RuntimeError` with context (device disconnected, USB error), preventing silent failures.
- **cJSON OOM fallback (L8)**: `bridge_serial.c` `cdc_write_json()` now sends a fixed-string `{"rsp":"error","ok":false,"error":"out_of_memory"}` when heap exhaustion prevents JSON serialization, instead of returning silently and leaving the host waiting.
- **Target name override race (L9)**: `bt_hid_host.c` `s_target_name_override[]` is now protected by a `portMUX_TYPE` spinlock — writes from the ctrl task and reads from the BT GAP callback (which can run on different cores on ESP32) no longer race.
- **Chord undo now handles all mapping modes (H2)**: when a chord completes, individual key actions for already-pressed member keys are now properly undone for turbo, sticky-mod, tap-hold, and double-tap modes — not just passthrough/remap/remap-HID. Previously only 3 of 9 modes were undone, leaving phantom key presses or orphaned timers.
- **FSM timeout recovery (M5)**: the Joy-Con setup FSM now has a periodic timeout check (every 500 ms). If a subcommand reply is lost for longer than 1500 ms, the FSM automatically advances to the next step instead of stalling indefinitely. Uses the already-defined `SETUP_TIMEOUT_MS` constant.
- **Calibration restore deferred until FSM ready (M6)**: stick calibration from SPI flash is no longer applied on the very first input report (when the setup FSM may still be reading calibration data). Instead, the restore is deferred until `joycon_setup_is_ready()` returns true, ensuring SPI factory calibration is available before falling back to NVS-saved data.
- **DEFAULT_KEYMAP populated with all 31 entries (M4)**: the helper-app's `DEFAULT_KEYMAP` dictionary in `hid_keycodes.py` now contains all 31 key_id → (modifier, keycode) entries matching `keymap.c` on the firmware. Previously only 7 of 31 entries were defined, causing the profile editor to show missing mappings.

### Added

- **Turbo (rapid-fire) mapping mode**: new `turbo` profile mapping type auto-repeats a key while held, toggling press/release at a configurable interval (10–500 ms, default 50 ms). Up to 8 concurrent turbo keys.
- **One-shot modifier mapping mode**: new `oneshot` profile mapping type arms a modifier on press. The next non-oneshot key press applies the armed modifier once, then auto-releases. 3-second timeout if no key follows. Up to 8 concurrent one-shot keys.
- **Timing humanization (anti-cheat)**: macro delays use ±15% random jitter, turbo repeats use ±10% jitter via one-shot timer re-arm (replaces periodic timer). Controlled by `"humanize"` profile field and `set_humanize` serial command. Enabled by default.
- **BT auto-reconnect**: on disconnect, the ESP32 BT host automatically attempts reconnection with exponential backoff (2 s → 4 s → 8 s). Configurable via Kconfig (`JOYCON_HOST_AUTO_RECONNECT`, `JOYCON_HOST_AUTO_RECONNECT_MAX_RETRIES`, default 3). Falls back to discovery after max retries. Status 6 ("reconnecting") forwarded to helper app.
- **SOCD mode expansion**: three Simultaneous Opposing Cardinal Direction cleaning modes — neutral (default, both cancel), last-input-wins, and first-input-wins. Configurable via `stick.socd_mode` profile field, `set_socd_mode` serial command, or UART ctrl command `0x07`.
- **Rapid trigger (stick hysteresis)**: separate activation (default 30) and deactivation (default 20) thresholds for stick-to-key mapping, preventing flickering at the deadzone boundary. Configurable via `stick.rapid_trigger` profile field, `set_rapid_trigger` serial command, or UART ctrl command `0x08`.
- **Sticky modifier mapping mode**: new `sticky` profile mapping type toggles a key on/off — first press activates, second press deactivates. Useful for held modifiers (Shift, Ctrl, Alt) that should stay active without physically holding.
- **Tap-hold mapping mode**: new `tap_hold` profile mapping type differentiates a quick tap from a long hold. Tap fires one action (press + release), hold fires a different action after a configurable threshold (50–2000 ms, default 300 ms). Up to 8 concurrent tap-hold keys.
- **Chord (combo) detection**: new top-level `chords` array in profiles defines multi-button combos (2–4 keys). When all chord keys are pressed simultaneously, a single chord action fires and the individual key mappings are suppressed. Up to 8 concurrent chords. Individual key actions for already-pressed chord members are undone (for simple modes) when a chord completes.
- **SHA-256 firmware integrity verification**: downloaded firmware binaries are hashed and verified against `sha256sums.txt` (when published as a GitHub release asset). Hash mismatch aborts the update immediately.
- **Download retry with backoff**: firmware downloads automatically retry up to 3 times with exponential backoff (1 s, 2 s, 4 s) on network failures.
- **Release notes in update dialog**: the firmware update confirmation dialog now shows the GitHub release notes (truncated to 600 chars) so users know what changed before updating.
- **Local `.bin` file flashing**: new "Flash from file…" button in the Firmware section lets users pick a local firmware binary and flash it directly. SHA-256 is computed and shown before flashing. Target board is auto-detected from the filename.
- **OTA rollback protection** (firmware): both boards now enable `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`. After an OTA update, the new firmware calls `fw_ota_mark_valid()` early in `app_main` — if it crashes before doing so, the bootloader automatically rolls back to the previous working partition.
- **First-time firmware flashing** (helper app): new "Initial Flash (new boards)" section with built-in esptool integration. "Download & flash latest" auto-detects the chip, downloads the latest firmware from GitHub Releases, erases flash, and programs the board in one click — no ESP-IDF installation needed. "Flash files…" lets users pick local bootloader + partition table + app binaries (or a merged binary). Boards must be in download mode (BOOT + RESET) for initial provisioning.
- **Flash verification**: all initial flash operations use esptool `--verify` to read back written data and confirm it matches the source file. Any mismatch aborts with a clear error message.
- **Firmware backup**: new "Backup flash…" button reads the entire flash contents (4 MB) and saves to a local `.bin` file before erasing. Allows recovery if something goes wrong during initial provisioning.
- **SHA-256 for all initial flash downloads**: bootloader, partition table, and app binaries are all verified against `sha256sums.txt` checksums during initial flash (not just OTA updates).
- **Port validation**: initial flash operations validate the COM port exists before attempting to connect, with a helpful error listing available ports.
- **Friendly esptool error messages**: common esptool failures (connection refused, permission denied, verification failure, timeout) are translated into user-friendly messages with actionable troubleshooting steps.
- **Initial flash troubleshooting** (Help tab): new troubleshooting entries for chip detection failures, verification errors, and missing esptool.
- **Joy-Con setup FSM** (`joycon_setup.c/.h`): after BT connection, the ESP32 now sends a sequence of subcommands to the Joy-Con — request device info → read factory stick calibration from SPI flash → read user stick calibration → set full report mode (0x30) → enable IMU → enable vibration → set player LEDs → READY. Inspired by the `bluepad32` and `BlueCubeMod` open-source implementations.
- **SPI flash stick calibration**: factory calibration data (addresses 0x603D/0x6046) and user calibration data (0x8010/0x801D, when magic bytes 0xB2/0xA1 are present) are read from the Joy-Con's onboard flash. This eliminates the warm-up period of the auto-calibration system — sticks are accurate immediately after connection.
- **Controller type detection**: device info reply identifies the connected controller as Joy-Con (L), Joy-Con (R), or Pro Controller. Type is available via `joycon_setup_get_type()`.
- **Serial number readback**: reads the controller serial number from SPI flash (address 0x6000, 16 bytes). Available via `joycon_setup_get_serial()`.
- **Controller colors**: reads body and button RGB colors from SPI flash (address 0x6050, 6 bytes). Forwarded to the helper app as hex `#RRGGBB` strings. Available via `joycon_setup_get_colors()`.
- **Stick deadzone parameters**: reads raw deadzone and range ratio from SPI flash (address 0x6086). Available via `joycon_setup_get_stick_params()`.
- **IMU calibration readback**: reads factory (0x6020) and user (0x8026) accelerometer/gyroscope calibration data from SPI flash. User calibration takes priority when magic bytes (0xB2 0xA1) are present. Available via `joycon_setup_get_imu_cal()`.
- **Controller info UART frame** (marker 0xF9): after setup FSM completes, the ESP32 sends a composite frame with all controller metadata (type, serial, colors, stick params, IMU cal) to the ESP32-S3. The ESP32-S3 emits this as an NDJSON `{"evt":"controller_info",...}` event over CDC serial.
- **HD Rumble support**: the helper app can send `{"cmd":"rumble","device_id":0,"freq":160,"amp":50}` to trigger vibration on the connected controller. Full log2-based frequency (41–1253 Hz) and amplitude (0–100%) encoding per the Nintendo specification. Safety clamp at 0xC8 to protect the linear resonant actuator.
- **Home LED control**: the helper app can send `{"cmd":"home_led","device_id":0,"brightness":8}` to set the Home button LED brightness (0–15). Left Joy-Con guard (has no Home button) returns a warning log.
- **Controller info bar** (helper app): the Controller tab now shows a compact info bar displaying controller type, serial number, body/button color swatches, stick deadzone, and range ratio. Data populates automatically when a controller connects. Resets on disconnect.
- **Rumble & Home LED controls** (helper app): the Controller tab now includes a "Controller features" section with a frequency/amplitude rumble test button and a Home LED brightness slider.
- **Player LED control**: after completing the setup handshake, the host sets Player 1 LEDs on the Joy-Con via subcommand 0x30.
- **Battery level reporting**: battery level (0–4) is parsed from 0x30 input reports and forwarded to the ESP32-S3 via a new UART frame type (marker 0xFA). The ESP32-S3 emits it as an NDJSON `{"evt":"battery"}` event over CDC serial.
- **Battery indicator in status bar** (helper app): the bottom status bar now shows a battery level indicator (🔋 with filled/empty bars) when battery data is available. Resets on disconnect.
- **Double-tap mapping type**: new `MAP_DOUBLE_TAP` mapping mode (firmware + helper app). Single-tap sends one key, quick double-tap sends a different key. Configurable timeout (default 300 ms). Firmware implements a per-key state machine (DT_IDLE → DT_FIRST_DOWN → DT_ARMED → DT_SECOND_DOWN) with esp_timer one-shot timers. Up to 8 simultaneous double-tap keys.
- **BT RSSI signal strength**: ESP32 periodically polls Bluetooth RSSI (every 5 s) via `esp_bt_gap_read_rssi_delta()`. Signal strength forwarded through the full stack: ESP32 → UART frame (marker 0xF8) → ESP32-S3 → NDJSON `{"evt":"rssi"}` → helper app status bar with signal bars (████/███░/██░░/█░░░) and dBm value.
- **Latency round-trip test**: helper app records `time.monotonic()` before sending ping, measures RTT on pong response. Auto-pings every 10 seconds. Status bar shows ⏱ Nms RTT.
- **Curated default profiles**: added Minecraft and Racing presets to the existing 3 (FPS/Shooter, Platformer, RPG/Action). Minecraft: WASD + Space/Shift/E/Q/1-4. Racing: arrows + N/B/R/M/Shift/Space.
- **Calibration wizard**: 3-step guided calibration dialog (center stick, sweep edges, save/clear). Accessible via 🔧 Calibrate button in Controller Features. Sends `{"cmd":"calibration","action":"save"|"clear"}` to firmware. Includes quick deadzone/curve adjustment sliders.

### Changed

- **3-panel "Heist Table" layout**: the Controller tab is now a three-panel view — Left: **Heist Library** (4 loadout cards with one-click switching, Import/Export buttons), Center: controller canvas (unchanged), Right: **Heist Tools** (context-sensitive panel showing the selected hotspot's name, current mapping, and one-click action buttons for Keyboard / Mouse / Trick / Mask Shift / Clear) plus a **Disguises** section with 5 quick-switch mask cards (Base Face + Mask 1–4). Panels stay synchronized: clicking a hotspot updates Heist Tools, clicking a mask card switches the active layer and redraws the canvas, clicking a loadout card switches slots and refreshes all panels.
- **Enhanced status bar**: now shows connection indicator (🔌 COMx / ⚠ Disconnected), active mask (🎭 Base Mask / Mask N), and latency (⏱ Xms when profiling enabled).
- **Window size**: default window geometry increased from 980×720 to 1280×760 to accommodate the 3-panel layout.
- **"Bind Bandit" UI identity system**: renamed all user-facing terminology across the helper app to match the heist/thief theme. Profile → **Loadout**, Layer → **Mask**, Macro → **Trick**, Mapping → **Heist Plan**, Bind → **Steal**, Apply → **Execute**, Sandbox → **Practice Run**, Learn → **Case**, Defaults → **Quick Job**. Successful binds now show "STOLEN ·" text in the ink stamp animation and status bar. All 14 Help tab sections updated to match. Internal variable names, method names, JSON protocol keys, and firmware code are unchanged.

### Added

- **Inline Trick Builder**: clicking "🧪 Trick (Macro)" in the Heist Tools panel now opens an inline trick editor (pick/create tricks, view/edit steps, assign to the selected hotspot) instead of the old mapping popup. The Tricks tab and inline builder stay in sync.
- **Comprehensive Help tab**: replaced the single pinout-image Help tab with a full 14-section collapsible help guide covering: What Is This, What You Need, Wiring & Connections, Board Pinout Diagram (embedded image preserved), Firmware Installation (ESP32-S3 then ESP32), First End-to-End Test, Using Bind Bandit, Default Key Mapping table, Serial Protocol reference, Mouse Configuration (M913 & Razer), OTA Firmware Updates, Troubleshooting (6 categories), Installing / Updating the Helper App, and a Quick Reference card. Includes a live search bar that filters sections by keyword. All sections are collapsible with toggle arrows.
- **Hand-drawn button overlays**: all per-button highlight overlays (5 devices, 158 buttons) regenerated in pencil-sketch style — wobbly circle outlines with cross-hatch fill. Now generated in 7 rainbow colours (red, orange, yellow, green, blue, indigo, violet) instead of the old default/dark theme split — 1106 total PNGs. Default colour is **violet**. Generator updated in `tools/generate_button_overlays.py`.
- **Rainbow colour picker**: a 🎨 dropdown in the Controller tab toolbar lets users choose their hotspot highlight colour from the 7 rainbow options. The selection is applied to the canvas hotspot circles, hover glow ring, ink stamp animation, and keyboard preview. Defaults to violet.
- **Popup-based UI refactor**: Controller, Mouse, and Razer tabs now show the device canvas as the dominant visual (fills all available space). Button mapping, DPI, LED, layers, chords, and other controls moved into on-demand popup panels (`SketchPopup`) opened via compact toolbar buttons. This replaces the crowded inline layout where controls pushed the device image into a small fixed-height strip.
- **SketchPopup class**: reusable themed popup (`tk.Toplevel`) with pencil-sketch aesthetic — hand-drawn title bar, themed background, toggle show/hide. Available for all tabs.
- **Pencil sketch UI assets**: generated hand-drawn popup frames, toolbar backgrounds, dividers, and corner doodles for both light and dark themes (8 new PNGs in `docs/ui/*/misc/`).
- **Muted theme colors**: accent, danger, warning, and selection colors toned down in both light and dark themes; button padding reduced for a less visually noisy interface.
- **Razer mouse support**: new `razer_device.py` module and **Razer** tab in Bind Bandit for configuring Razer Basilisk X HyperSpeed mice (and other supported models) over USB HID Feature Reports. Supports battery readback, DPI stages (5 levels, X/Y independent), polling rate, idle timeout, and **on-device button remapping** (7 buttons → keyboard keys, mouse buttons, DPI cycle, or disable). All settings are written to the mouse's onboard memory — no Synapse, no drivers, anti-cheat safe. Includes profile save/load/delete with per-device auto-linking, and Read State to pull live configuration from the device. Protocol based on the 90-byte Razer USB HID specification reverse-engineered by the OpenSnek project.
- **Mouse overlay hotspots**: updated `MOUSE_HOTSPOTS` labels to match `razer_device.BUTTON_SLOTS` naming (lowercase with underscores) for overlay integration.

- **Composited device backgrounds**: the Controller and Mouse tab canvases now fuse the device overlay PNG onto the app background image at runtime using Pillow alpha-compositing. Instead of a floating overlay on a solid-colour canvas, each tab shows a seamless background with the device baked in — tooltips and hotspot controls now line up with the device image. Falls back to the previous overlay-only rendering when Pillow is unavailable.

- **IncediusMod mouse overlay support**: M913 Mouse tab now uses layout-specific overlay images — Stock M913 (`m913.png` / `m913-none.png`) or IncediusMod (`m913_Incedius.png` / `m913_Incedius-none.png`) — selected automatically when the user switches layout mode. Switching layout mode live reloads the overlay instantly.
- **Dark mode overlay images**: both M913 and Joy-Con overlay finders now select dark-variant PNGs when dark mode is active, matching the background theme.

- **Hover glow on hotspots**: moving the mouse over controller diagram hotspots now draws a dual-ring hand-drawn glow (outer dashed, inner solid) in the accent colour.
- **Bind overlay card**: entering press-to-bind mode now shows a floating card on the canvas with the hotspot name and current binding, styled to match the sketch theme.
- **Ink stamp animation**: a successful bind triggers an expanding dashed ring + floating checkmark animation (8 frames, 50 ms each) as visual confirmation.
- **Visible layer tab bar**: sketch-styled layer tabs are now displayed below the controller diagram, letting you click to switch the active editing layer without opening the layer popup.
- **Restore last config**: a "Restore…" toolbar button reverts the profile to the last state successfully written to the device. The snapshot is taken automatically after each successful device write.

### Removed

- **Dead SVG files**: removed 6 SVGs (`background.svg`, `background-dark.svg`, `components.svg`, `components-dark.svg`, `icons.svg`, `icons-dark.svg`) that were never rendered at runtime (Tkinter has no SVG support).
- **Standalone snippet files**: removed `layout_snippet.py` and `ttk_style_snippet.py` (doc-only reference files, superseded by the live app code).
- **SVG infrastructure in bundle generator**: removed `_read_text()`, `_rewrite_bundle_svg()`, `_resolve_bg_paths()`, and all SVG-related CLI arguments from `generate_ui_bundle.py`. Bundles are now PNG-only.

### Changed

- `generate_ui_artifacts.py`: updated `UI_BUNDLE_INPUTS` to reference Incedius overlays instead of deleted SVGs.
- `docs/ui/README.md`: updated to reflect PNG-only bundles, Incedius overlays, and removed snippet references.

### Added

- **App background image**: the helper app now displays a full-window background image (light and dark variants) behind the UI. Images scale to cover the window on resize using Pillow. Background PNGs are discovered from `docs/ui/`, `.ui-bundle/`, or the frozen bundle and are selected automatically based on the active theme (light/dark).
- **Full Joy-Con button support (Nintendo 0x30 reports)**: expanded from 7 key_ids (WASD + jump/sprint/crouch) to 25 key_ids covering all Joy-Con buttons — face buttons (A/B/X/Y), shoulders (L/R), triggers (ZL/ZR), system (Plus/Minus/Home/Capture), stick clicks, and right stick virtual directions. All button bitmask definitions added to `nintendo_candidate.h`.
- **Stick auto-calibration**: replaced the fixed center value (2048) with per-axis auto-calibration that tracks min/center/max at runtime. The first 8 samples establish the center via running average, then min/max expand as the stick reaches its limits. Raw values are normalized to a ±4096 scale for deadzone comparison. Inspired by GamepadPhoenix's `StickCal` approach.
- **Right stick → key events**: right stick now emits directional key_ids (22–25), mapped to arrow keys by default. Useful for camera/look controls or as remappable UI navigation.
- **Default keymaps for all buttons**: new key_ids have sensible defaults for FPS-style games (A→E, B→Q, X→R, Y→F, L→Tab, Plus→Escape, etc.). All mappings are overridable via the profile system / helper app.
- **Code signing + cosign support** — CI workflow now optionally signs the EXE with Authenticode (via `CODESIGN_PFX_BASE64` / `CODESIGN_PFX_PASSWORD` GitHub Secrets) and publishes Sigstore/cosign keyless provenance signatures. Added `scripts/new-self-signed-codesign-cert.ps1`, `scripts/pfx-to-base64.ps1`, and `scripts/sign.ps1` for local signing workflows.

### Changed

- **Performance: diff-based keymap canvas**: hotspot redraws now update items in-place via `itemconfigure`/`coords` instead of `canvas.delete("all")` + full rebuild. Full rebuilds only happen on resize or profile change.
- **Performance: dirty-flag batched redraw**: incoming `mapped_key` events set a dirty flag; the 80 ms pulse tick coalesces redraws instead of redrawing on every single input event.
- **Performance: cached conflict detection**: `_detect_conflicts()` result is cached and only invalidated on profile/mapping changes, not on every redraw.
- **Performance: cached reverse lookup**: `key_id → hotspot name` mapping is cached with explicit invalidation instead of rebuilding a dict on every input event.
- **Performance: lazy tab loading**: only Profile and Controller tabs are built at startup; Macros, Stick, Share, Overlay, and Input Test tabs are deferred until first selection.
- **Performance: O(1) firmware layer override lookup**: `find_layer_override()` now uses a per-layer `override_index[256]` array instead of linear scan (+1 KB RAM total for 4 layers).
- **Performance: timeline skip-if-unchanged**: timeline canvas skips redraw when event count hasn't changed and less than 1 second has elapsed.

- **CI: Node.js 24 migration**: upgraded all GitHub Actions to Node 24-compatible versions to resolve deprecation warnings:
  - `actions/checkout` v4 → v5
  - `actions/setup-python` v5 → v6
  - `actions/upload-artifact` v4 → v6
  - `actions/download-artifact` v4 → v7

### Fixed

- **Firmware build: flash size mismatch**: both ESP32 and ESP32-S3 `sdkconfig.defaults` now set `CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y`. The OTA-enabled partition table requires ~3.6 MB, which exceeded the 2 MB default and caused CI build failures.
- **ESP32-S3 build: missing TinyUSB component**: `tinyusb` was removed from ESP-IDF v5.2 built-in components. Added `idf_component.yml` to pull `espressif/esp_tinyusb` from the component registry, and updated `PRIV_REQUIRES` from `tinyusb` to `esp_tinyusb`.
- **ESP32-S3 build: `tud_task` implicit declaration**: removed the manual `tud_task()` call from `app_main.c` — `esp_tinyusb` v1.x runs it in its own internal FreeRTOS task after `tinyusb_driver_install()`. Replaced with `vTaskDelay(1)` to yield the main loop.
- **ESP32-S3 link: undefined TinyUSB HID callbacks**: the TinyUSB HID device class requires application-defined callbacks (`tud_hid_descriptor_report_cb`, `tud_hid_get_report_cb`, `tud_hid_set_report_cb`) which are implemented in `tusb_desc.c`. The linker couldn't resolve them due to archive link ordering. Added `WHOLE_ARCHIVE` flag to `main` component's `CMakeLists.txt` so all callback implementations are always linked.
- **ESP32 build: missing `driver` component + Bluetooth not enabled**: `driver/uart.h` required adding `driver` to `PRIV_REQUIRES` in `CMakeLists.txt`. Additionally, `sdkconfig.defaults` had no Bluetooth config, so the `bt` component didn't export its headers in CI (clean builds). Added `CONFIG_BT_ENABLED`, `CONFIG_BTDM_CTRL_MODE_BR_EDR_ONLY`, `CONFIG_BT_BLUEDROID_ENABLED`, `CONFIG_BT_CLASSIC_ENABLED`, and `CONFIG_BT_HID_HOST_ENABLED`.
- **ESP32 build: cast-to-array-type + undeclared Kconfig macros**: `esp_bt_hid_host_connect((esp_bd_addr_t)bda)` failed because `esp_bd_addr_t` is `uint8_t[6]` — C forbids casting to array types. Changed to `(uint8_t *)bda`. Additionally, `CONFIG_JOYCON_HOST_UART_DEBUG_REPORTS` (default `n`) and `CONFIG_JOYCON_HOST_UART_DEBUG_MAX_BYTES` are not defined as C macros when disabled; switched from runtime `if()` to `#if` preprocessor guards.
- **ESP32-S3 link: multiple-definition of TinyUSB descriptor callbacks**: `espressif__esp_tinyusb` v1.7.6 provides strong (non-weak) implementations of `tud_descriptor_device_cb`, `tud_descriptor_configuration_cb`, and `tud_descriptor_string_cb` in `descriptors_control.c`. Our `tusb_desc.c` also defined them, causing linker errors with the `WHOLE_ARCHIVE` flag. Removed the three conflicting callbacks from `tusb_desc.c` and instead pass our custom descriptors through `tinyusb_config_t` to `tinyusb_driver_install()`, which makes `esp_tinyusb`'s callbacks serve our descriptor data.
- **ESP32 link: missing Kconfig parent for HID Host**: `CONFIG_BT_HID_HOST_ENABLED=y` was set in `sdkconfig.defaults` but its parent menuconfig `CONFIG_BT_HID_ENABLED=y` was missing. Without the parent, Kconfig silently ignored the child option, so `BTC_HH_INCLUDED` evaluated to `FALSE` and all `esp_bt_hid_host_*` function bodies were compiled out of `libbt.a`, causing undefined reference linker errors. Added the missing `CONFIG_BT_HID_ENABLED=y`.

### Added

- **IncediusMod layout mode** (Mouse tab): optional alternative button label set for the [Red Dragon M913 mod by Incedius](https://www.printables.com/model/1191307-red-dragon-m913-mod). A "Layout" dropdown in the Device section switches between "Stock M913" and "IncediusMod". Both modes now use the same Side 1–12 button identifiers to match the original M913 naming. The layout choice is saved per-profile and labels update instantly.

- **App icon**: converted `icon.png` (1024×1024 sketchbook-ink artwork) to a multi-size `icon.ico` (16–256 px) at `helper-app/icon.ico`. Used as the window icon at runtime and embedded in the PyInstaller `.exe`.

- **Help tab with pinout diagram**: new "Help" tab (lazy-loaded) displays the `pinouts.png` board pinout reference for the Arduino Nano ESP32-S3 and NodeMCU ESP32-WROOM-32 in a scrollable canvas with horizontal/vertical scroll and mouse-wheel support. Image is bundled through the UI bundle pipeline.

- **M913 mouse overlay artwork**: four sketchbook-ink themed M913 overlay PNGs (light connected/disconnected, dark connected/disconnected) wired into the Mouse tab, matching the Joy-Con overlay pattern in the Controller tab. The UI bundle generator and artifact generator now include M913 images alongside Joy-Con overlays.

- **Redragon M913 Impact Elite mouse support** (helper app):
  - New `m913_device.py` module: full USB HID protocol ported from C++ (`m913-ctl` by Qehbr / `mouse_m908` by dokutan) to Python using `hidapi`.
  - Anti-cheat safe: all button remapping is written to the mouse's onboard microcontroller memory — no software injection.
  - 16-button remapping: mouse actions, keyboard keys/combos (Ctrl+C etc.), multimedia keys, DPI controls, fire mode.
  - 5-slot DPI configuration (100–16000 in steps of 100) with per-slot enable/disable.
  - LED modes: off, steady (color + brightness), respiration (color + speed), rainbow.
  - Polling rate: 125 / 250 / 500 / 1000 Hz.
  - **Multi-device support**: auto-detects all connected M913 mice (via wireless receiver VID `0x25a7` / PID `0xfa07`); each device configurable independently.
  - **Sister profiles**: link an M913 profile to a Joy-Con slot (1–4) so mouse config can travel with controller mappings.
  - M913 profiles saved as JSON to `%APPDATA%/BindBandit/m913/` with per-device registry.
  - New "Mouse" tab (lazy-loaded) with device scanner, button mapping grid, DPI editor, LED picker, polling rate selector, and profile save/load/delete.
  - Graceful fallback when `hidapi` is not installed (tab shows install hint, rest of app unaffected).
  - Added `hidapi>=0.14` to `requirements.txt` and `hid` to PyInstaller hidden imports.

- **Auto-advance unbound hotspot**: after binding a hotspot, the editor automatically selects the next unbound hotspot in layout order for faster mapping.
- **Latency profiling mode** (Input Test tab): toggle checkbox displays real-time redraw frame time and input processing latency (avg/max over last 50 samples).
- **Faster guided wizard**: auto-advance delay reduced from 600 ms to 300 ms for snappier step-by-step flow.

- **Auto-update date guard**: both the helper-app updater and the firmware updater now compare the GitHub release `published_at` timestamp against a build date (`__build_date__`) embedded at CI time. If the running build is newer than the latest release, the update is skipped even if version numbers would suggest otherwise. Local dev builds (empty `__build_date__`) fall back to version-only comparison.

- **Unified click-to-bind** (helper app):
  - Single-click a hotspot: auto-enters learn mode (unbound) or bind mode (bound) — no separate Learn/Bind steps.
  - Right-click context menu on any hotspot: Learn, Bind, Reset to passthrough, Clear binding, Disable.
- **Pulse animation**: active controller hotspots pulse with a breathing glow effect (80 ms timer, phase 0.3–1.0).
- **Profile slot quick-select**: 4 slot buttons at top of Profile tab with names; "Read all names" to refresh.
- **Safe mode recovery**: one-click button resets the active device slot to defaults (with confirmation dialog).
- **Tap-hold mapping type**: single button produces different actions for quick tap vs long hold (`hold_ms` threshold, default 300 ms).
- **Chording**: define multi-button combos that trigger a single action when pressed simultaneously. New `chords` profile field.
- **Conflict auto-fix**: when duplicate output bindings are detected, a "Fix" button resolves by keeping the first and clearing the rest.
- **Visual event timeline** (Input Test tab): horizontal canvas showing the last 5 seconds of input events as colored marks with a time axis.
- Theme version 2 with new state color tokens: `active`, `conflict`, `modified`, `selected`, `pulse_bright`, `timeline_press`, `timeline_release`.

- **Undo / Redo** (Ctrl+Z / Ctrl+Y): stack-based profile change history (up to 50 levels); buttons in the status bar.
- **Guided Setup wizard**: step-by-step Toplevel dialog learns 7 controller buttons and auto-binds WASD/Space/Shift/Ctrl.
- **Intent-based mapping**: right-click "What should X do?" menu with 14 common game actions (Jump/Space, Sprint/Shift, etc.).
- **Smart Defaults**: auto-applies WASD/Space/Shift/Ctrl/E/R/V to D-pad + face buttons when a controller connects and profile is mostly empty.
- **Smart Search**: search bar in keymap editor filters hotspots by name, output, or mapping type; matching hotspots get a dashed highlight ring.
- **Sandbox mode**: checkbox to enter temporary playground mode; on exit, user chooses to keep or discard changes.
- **Ghost labels on hover**: faint italic tooltip follows cursor over the controller diagram showing hotspot name + current output.
- **Visual layer stack**: row of badges below layer radio buttons displaying each layer's name, mode, and mapping count.
- **Explain mapping dialog**: right-click → shows full input→output chain, conflicts, and layer overrides in a scrollable Toplevel.
- **Lock critical inputs**: right-click Lock/Unlock prevents accidental unbinding; locked hotspots require yes/no confirmation.
- **Feedback sounds**: optional Windows beep on bind (800 Hz), unbind (400 Hz), error (300 Hz), undo (600 Hz); background thread, graceful fallback.
- **Adaptive UI (Simple/Advanced)**: toggle hides layers, chords, Macros/Stick/Share tabs in simple mode for cleaner first-time experience.
- **Mode indicator**: always-visible status bar showing active slot, layer, bind/learn mode, sandbox, UI mode, undo depth; refreshes every 300 ms.
- **Community presets** (Share tab): three built-in mapping presets (FPS/Shooter, Platformer, RPG/Action) with one-click apply.

- **Press-to-bind remapping** (helper app + firmware):
  - New `remap_hid` mapping type: bypasses compiled `keymap.c` entirely, sends arbitrary USB HID modifier + keycode directly.
  - Controller tab "Bind key" button: click a hotspot, press any keyboard key, instantly mapped.
  - `hid_keycodes.py` module: ~100 tkinter keysym → USB HID keycode mappings with reverse lookup.
- **Layer system** (firmware + helper app):
  - Profiles can define up to 4 overlay layers, each activated by a controller button (hold or toggle mode).
  - Layer overrides are sparse: only listed key_ids are overridden, others fall through to base.
  - Firmware emits `{"evt":"layer","name":"...","active":true/false}` events over CDC serial.
  - Controller tab has layer selector (Base + Layer 1–4), activation key_id/mode/name configuration.
- **Live input visualization**: controller hotspots light up green when the corresponding button is physically pressed.
- **Conflict detection**: hotspots producing the same output key are highlighted red, with a conflict summary below the editor.
- **Color-coded hotspots**: green = active, red = conflict, blue = selected, yellow = has custom mapping.
- **Input Test tab**: real-time event log showing controller button presses/releases with timestamps and active-key summary.
- **Profile management**: rename, duplicate, and reset-to-defaults buttons on the Profile tab.
- **Reset button**: per-hotspot "Reset button" reverts individual mappings to passthrough.

- **Logging & crash-log infrastructure** (`helper-app/joycon_helper/logger.py`):
  - `logs/` folder with daily rotating `helper.log` (kept 15 days).
  - `crash-logs/` folder with timestamped crash dumps for unhandled exceptions (main thread + worker threads).
  - Auto-cleanup: files older than 15 days deleted on each startup.
  - No personal data collected — only app-level events, serial traffic, and platform info.
- Logging integrated into `app.py` (serial connect/disconnect, command TX/RX, profile load/save, theme loading, startup/shutdown) and `serial_client.py` (port open/close, read errors, RX thread lifecycle).
- `_log_line()` now writes to both the UI log widget and the file logger.
- **Auto-update** (`helper-app/joycon_helper/updater.py`):
  - On startup (and on manual click), checks GitHub Releases API for a newer version.
  - When running as a frozen `.exe`: downloads, swaps in place (rename dance), and prompts restart.
  - Version displayed in the sidebar; update button changes to show available version.
  - No personal data sent — unauthenticated GET to the public GitHub API only.
- **Runtime version** (`helper-app/joycon_helper/_version.py`):
  - Auto-generated by `tools/versioning.py write-app-version`.
  - Pre-commit hook and CI both keep it in sync with `version.json`.
- **Release workflow**: `build-release-bundle.yml` now supports `create_release: true` dispatch input.
  - Validates that the new version strictly increments over the latest GitHub Release tag.
  - Creates a GitHub Release tagged `v{version}` with `BindBandit.exe` as a downloadable asset.
- **Dark controller overlay artwork**: `joycons-dark.png` + `joycons-dark-grey.png` source PNGs for the dark theme.
  - Artifact pipeline now generates 4 dark inspection copies (`joycons-dark-none/left/right/both.png`) alongside the 4 light copies.
  - Dark UI bundle (`.ui-bundle-dark/`) now uses the dark overlay PNGs instead of the light ones.
  - `background-dark.svg` updated to reference `joycons-dark.png`.
- **Dark theme restyle — dark blue ballpoint pen**: all dark SVGs, theme tokens, and helper-app colors shifted from warm sepia/gold to a cool dark-blue-on-dark-paper aesthetic matching `joycons-dark-grey.png`.
- **Dark mode UI bundle**: complete dark-mode variant of the torn-parchment theme.
  - `docs/ui/background-dark.svg` — dark parchment on very dark desk surface.
  - `docs/ui/assets/components-dark.svg` — dark-inverted component sheet (same shapes/paths as light).
  - `docs/ui/assets/icons-dark.svg` — dark-inverted icon sheet (same shapes/paths as light).
  - `DARK_THEME` tokens in `tools/generate_ui_bundle.py` with inverted color palette.
  - `DARK_UI_THEME` in `helper-app/joycon_helper/app.py` with auto-detect support.
- Bundle generator now produces **two** bundles by default: `.ui-bundle/` (light) and `.ui-bundle-dark/` (dark). Use `--no-dark` to skip the dark bundle.
- Dark mode auto-detection: `JOYCON_THEME=dark` env var, `--dark` CLI flag, or Windows 10+ `AppsUseLightTheme` registry check.
- CI workflow and PyInstaller command updated to include dark bundle in builds.

## 2026-04-04

### Added

- Two-board “anti-cheat-safe” architecture documentation: ESP32 (Bluetooth Classic HID host) → UART → ESP32-S3 (USB HID keyboard).
- Detailed one-USB-dongle setup docs:
  - `docs/wiring.md` (power + UART wiring, one-USB power model, exact pin-to-pin table matching `pinouts.png`)
  - `docs/firmware-install.md` (Windows + ESP-IDF flashing guide for both boards)
- Arduino Nano ESP32-S3 (ABX00083) setup notes with GPIO mapping:
  - `RX0 = GPIO44`, `TX0 = GPIO43`
- Helper app (Windows, Python + Tkinter): tabbed UI for profiles/macros/share/overlay + NDJSON serial protocol documentation.
- ESP32 Classic-BT host improvements for evidence-first input capture:
  - Configurable target name substring for discovery (Joy-Con/Binbok/third-party)
  - Report logging “on change”
  - Optional UART debug frames forwarding raw HID reports (ESP32-S3 ignores them)
- Offline UART log decoder updates to understand both key-event frames and optional debug frames.

### Changed

- Repo documentation aligned around the **one USB dongle** flow (ESP32-S3 is the only board that plugs into the PC).
- VS Code IntelliSense improvements by exporting and using `compile_commands.json` for ESP-IDF projects.

### Removed

- Legacy USB keyboard/device firmware path (project is ESP32-S3-only on the USB keyboard/device side).

### Docs / repo presentation

- `pinouts.png` used as the banner image at the top of the repository `README.md`.
