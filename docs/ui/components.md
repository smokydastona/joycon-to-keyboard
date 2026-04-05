# UI components (theme-matched)

This file describes how buttons/toggles/dials/icons should match the `sketchbook-ink` theme tokens.

- Theme tokens: generate a bundle with `python tools/generate_ui_bundle.py --out ./.ui-bundle` then use `./.ui-bundle/theme.json`
- Icon set (SVG): `docs/ui/assets/icons.svg`
- Component sheet (SVG): `docs/ui/assets/components.svg`

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
