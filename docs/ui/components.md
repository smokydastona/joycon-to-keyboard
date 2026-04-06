# UI components (theme-matched)

This file describes how buttons/toggles/dials/icons should match the `sketchbook-ink` theme tokens.

- Theme tokens: generate a bundle with `python tools/generate_ui_bundle.py --out ./.ui-bundle` then use `./.ui-bundle/theme.json`
- Icon set (SVG): `docs/ui/misc/icons.svg`
- Component sheet (SVG): `docs/ui/misc/components.svg`

## Icons

Use the icon set for:

- Port refresh
- BT status / connect
- Upload / download profile
- Warnings/errors

Guidelines:

- Stroke-based icons should feel hand-drawn: slightly irregular outlines, doubled construction strokes, and a little asymmetry are preferred over perfect geometry.
- Keep stroke width broadly consistent (~2.5px in SVG), but allow small wobble and ghost lines so the set reads like sketchbook marks instead of vector icons.
- Use semantic token colors:
  - `accent` for primary actions
  - `accent2` for success
  - `warning` for warnings
  - `danger` for errors
  - `muted` for secondary/disabled

## Buttons

Button variants (semantic):

- Secondary: panel-like button for non-destructive actions.
- Primary: accent-filled button for main actions (e.g. Connect/Scan, Upload+Activate).
- Danger: danger-filled for destructive actions.
- Disabled: reduced opacity.

Visual direction:

- Prefer uneven pill/button outlines over mathematically perfect rounded rectangles.
- Use faint second-pass strokes, hatch fills, or paper-noise overlays where helpful.
- Components should look like marker-and-pen UI sketches pinned on a workbench, not polished design-system tokens.

In Tkinter:

- Use `tk.Button` when you need strict colors.
- Use `ttk.Button` when you want OS-native behavior; accept that colors may vary.

## Toggles

Use for feature flags (e.g. record mode, debug options):

- Track: `panel2` + `border`
- Knob: `text`
- On state glow: `accent` at low opacity

Tkinter note:

- `ttk.Checkbutton` is the functional toggle; if you want a modern slider-toggle look, implement a small `Canvas` toggle using these colors.

## Dials / Sliders

Use for continuous parameters (deadzone, exponent):

- Ring: `border`
- Active arc: `accent`
- Needle: `text`
- Ticks: `muted` at low opacity

Tkinter note:

- `ttk.Scale` is the simplest control.
- For a true dial, draw on `Canvas` and map mouse drag to value.

## Status pills

Use for small status surfaces (BT state, active slot, connected port):

- OK: `accent2` background (low opacity) + `accent2` border
- Warning: `warning` background (low opacity) + `warning` border
- Error: `danger` background (low opacity) + `danger` border

## Pulse animation (hotspots)

Active controller hotspots use a pulse animation to draw attention. The pulse cycles between `accent2` and `pulse_bright` using linear interpolation on an 80 ms timer. The effect is a subtle breathing glow.

- Phase range: 0.3 → 1.0 → 0.3
- Hotspot fill blends between `accent2` (base) and `pulse_bright` (peak)
- A dashed oval ring is drawn around the pulsing hotspot

## Event timeline (Input Test tab)

A horizontal canvas showing the last 5 seconds of input events as colored markers:

- Press events: `timeline_press` color
- Release events: `timeline_release` color
- Time axis rendered with tick marks every second
- Redraws every 200 ms

## Slot quick-select (Profile tab)

A row of 4 buttons representing profile slots 0–3. Each button shows the slot name (or a default label). Clicking a slot sends `read_profile` for that slot and loads it into the editor.

## Context menu (Controller tab)

Right-click any hotspot to get a context menu with:

- Learn — enter learn mode for the hotspot
- Bind key — enter bind mode (press any keyboard key)
- Reset to passthrough — clear custom mapping
- Clear binding — remove the hotspot entirely
- Disable — set mapping to `disable` type
- What should X do? — intent-based mapping menu (common game actions)
- Explain mapping — show full input→output chain in a dialog
- Lock/Unlock — prevent accidental unbinding of critical inputs

## Undo / Redo (Ctrl+Z / Ctrl+Y)

A stack-based undo/redo system tracks profile changes. Up to 50 states are stored as JSON snapshots. The status bar shows undo depth. Undo/redo buttons are in the bottom status bar.

## Mode indicator (status bar)

An always-visible bottom bar showing: active slot, current layer, bind/learn mode, sandbox status, UI mode (simple/advanced), and undo depth. Refreshes every 300 ms.

## Adaptive UI (Simple / Advanced)

A toggle in the status bar switches between simple and advanced modes. Simple mode hides: layer configuration, chord section, Macros/Stick/Share tabs, and other power-user widgets. This reduces overwhelm for first-time users.

## Guided setup wizard

A Toplevel dialog that walks through 7 common game actions (Forward, Back, Left, Right, Jump, Sprint, Crouch). Each step prompts the user to press a controller button, then auto-binds a default WASD/Space/Shift/Ctrl mapping. Can be opened from the "Guided Setup" button in the keymap editor.

## Intent-based mapping

Right-click a hotspot → "What should X do?" shows a menu of 14 common game actions (Move Forward/W, Jump/Space, Sprint/Shift, etc.). Selecting one auto-applies a `remap_hid` mapping.

## Smart defaults

Automatically applies WASD+Space+Shift+Ctrl+E+R+V default mappings to common hotspots (D-pad, face buttons) when a controller connects and the profile is mostly empty.

## Smart search (keymap editor)

A search bar above the controller diagram filters hotspots by name, output key name, or mapping type. Matching hotspots get a dashed accent-colored ring on the canvas.

## Sandbox mode

A checkbox that enters a "playground" mode — all changes are temporary. When disabled, the user is asked whether to keep or discard changes. Snapshot/restore pattern.

## Ghost labels (hover)

Moving the mouse over the controller diagram shows a faint italic tooltip near the hovered hotspot, displaying its name and current mapping output.

## Visual layer stack

A row of labeled badges below the layer radio buttons showing each layer's name, mode, and mapping count. Updates when layers are added/removed or mappings changed.

## Explain mapping dialog

A Toplevel dialog showing the full mapping chain for a hotspot: input name → key_id → mapping type → output → conflicts → layer overrides. Opened from the right-click context menu.

## Lock critical inputs

A confirmation dialog prevents accidental unbinding of locked hotspots. Lock/unlock via the right-click context menu. Locked hotspots require a yes/no confirmation before reset/clear/disable.

## Feedback sounds

Optional Windows beep sounds on bind (800 Hz), unbind (400 Hz), error (300 Hz), and undo (600 Hz). Uses `winsound.Beep` in a background thread. Gracefully degrades on non-Windows platforms.

## Community presets (Share tab)

Three built-in preset profiles: FPS/Shooter, Platformer, and RPG/Action. Each applies a ready-made set of `remap_hid` mappings to known hotspots. Requires confirmation before applying.
