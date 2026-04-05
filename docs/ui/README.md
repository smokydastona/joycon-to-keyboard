# Helper App UI Pack (Tkinter)

This folder provides requested UI artifacts for the **helper app** (`helper-app/joycon_helper/app.py`).

Deliverables in this pack:

- UI mockup: see below
- UI background: `background.svg`
- UI theme: `bundle-example/theme.json`
- UI generator: `tools/generate_ui_bundle.py`
- UI bundle example: `bundle-example/`
- UI layout snippet: `layout_snippet.py`
- UI architecture diagram: `architecture.md`

UI kit (theme-matched controls):

- Icons: `assets/icons.svg`
- Components sheet (buttons/toggles/dials/pills): `assets/components.svg`
- Component guidance: `components.md`
- ttk styling snippet: `ttk_style_snippet.py`

---

## UI mockup (single window)

Goal: keep the current helper app UX, but make it easy to understand where things live.

```
+-----------------------------------------------------------------------------------+
| JoyCon Bridge Helper                                              [Connect/Disc] |
| Port [ COMx v ]  Baud [115200]  [Refresh]  [Connect/Disconnect]     BT: connected |
+---------------------------------------------+-------------------------------------+
| Tabs                                        | Actions                             |
| [Profile] [Macros] [Stick] [Share] [Overlay]| Slot [0 v]                           |
| [Controller]                                | [Ping]                              |
|                                             | [Upload profile to slot]            |
| (Tab content area)                          | [Upload + Activate]                 |
|                                             | [Read profile from slot]            |
|                                             | [Set active slot]                   |
|                                             |                                     |
|                                             | Raw command (JSON line)             |
|                                             | [ ......................... ]       |
|                                             | [Send]                              |
+---------------------------------------------+-------------------------------------+
| Device log / events                                                               |
| [scrolling log; shows JSON lines or plain text]                                   |
+-----------------------------------------------------------------------------------+
```

### Controller tab mock

```
[ BT banner background changes: Left / Right / Both ]

Controller connection

Preset: [ Either (Joy-Con) v ]   Target name contains: [ Joy-Con ............... ]

[Connect / Scan]

Note: board buttons are not required, but your Joy-Con may still need sync/pairing mode.
```

---

## Theme

Tkinter does not have a full CSS pipeline, so the theme here is expressed as **tokens** you can apply consistently:

- `theme.json` contains:
  - semantic colors (bg, panel, text, accent, danger, etc.)
  - spacing + radii hints (used for consistent padding)
  - typography hints (font family/size)

This pack does **not** force the app to load the theme automatically (to avoid changing runtime behavior). It is designed so you can adopt it incrementally.

---

## Background

`background.svg` is a lightweight vector background designed to:

- be non-distracting (so logs and JSON remain readable)
- fit a 980x680-ish canvas (current default window size)
- avoid any brand/trademark graphics

---

## UI generator

See `tools/generate_ui_bundle.py`.

It writes a “UI bundle” folder containing:

- `theme.json`
- `background.svg`
- `layout.json`
- `README.md`

Example:

```powershell
python tools/generate_ui_bundle.py --out docs/ui/bundle-example
```

---

## Bundle example

`bundle-example/` is a checked-in example output from the generator.

---

## Layout snippet

See `layout_snippet.py` for a minimal Tkinter layout skeleton that matches the current app’s structure.
