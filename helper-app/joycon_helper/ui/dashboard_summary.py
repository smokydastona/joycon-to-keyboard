from __future__ import annotations


def mapped_input_preview(profile: dict, *, limit: int = 4) -> str:
    mappings = profile.get("mappings", {})
    if not isinstance(mappings, dict) or not mappings:
        return "No mapped inputs yet"

    names = sorted(str(name) for name in mappings)
    visible = names[:limit]
    overflow = len(names) - len(visible)
    if overflow > 0:
        return ", ".join(visible) + f" +{overflow} more"
    return ", ".join(visible)


def build_profile_briefing(profile: dict, slot: int) -> dict[str, str]:
    name = str(profile.get("name") or f"Slot {slot}")
    icon = str(profile.get("icon") or "🎒")
    mappings = profile.get("mappings", {})
    macros = profile.get("macros", [])
    layers = profile.get("layers", [])
    chords = profile.get("chords", [])
    tags = [str(tag).strip() for tag in profile.get("tags", []) if str(tag).strip()]
    stick = profile.get("stick", {}) if isinstance(profile.get("stick", {}), dict) else {}
    curve_type = str(stick.get("curve_type") or "linear").replace("_", " ").title()

    mapping_count = len(mappings) if isinstance(mappings, dict) else 0
    macro_count = len(macros) if isinstance(macros, list) else 0
    layer_count = len(layers) if isinstance(layers, list) else 0
    chord_count = len(chords) if isinstance(chords, list) else 0

    return {
        "slot": f"Slot {slot}",
        "name": f"{icon} {name}",
        "counts": (
            f"{mapping_count} mapped | {macro_count} macro(s) | "
            f"{layer_count} layer(s) | {chord_count} chord(s)"
        ),
        "details": (
            f"Tags: {', '.join(tags) if tags else 'None'} | Stick curve: {curve_type}"
        ),
        "preview": f"Mapped inputs: {mapped_input_preview(profile)}",
    }


def battery_text(level: int | None) -> str:
    if level is None:
        return "—"
    clamped = max(0, min(level, 4))
    return f"{'█' * clamped}{'░' * (4 - clamped)} ({clamped}/4)"


def build_battery_briefing(levels: dict[int, int]) -> dict[str, str]:
    left = levels.get(0)
    right = levels.get(1)
    headline = f"L {left if left is not None else '—'}/4 | R {right if right is not None else '—'}/4"
    details = f"Left {battery_text(left)} | Right {battery_text(right)}"
    return {
        "headline": headline,
        "details": details,
    }
