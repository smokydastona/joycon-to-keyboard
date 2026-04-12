from __future__ import annotations

_BASE_KEY_LABELS: dict[int, str] = {
    1: "Forward",
    2: "Back",
    3: "Left",
    4: "Right",
    5: "Jump",
    6: "Sprint",
    7: "Crouch",
    8: "A",
    9: "B",
    10: "X",
    11: "Y",
    12: "L",
    13: "R",
    14: "ZL",
    15: "ZR",
    16: "Plus",
    17: "Minus",
    18: "Home",
    19: "Capture",
    20: "LStick",
    21: "RStick",
    22: "RStick Up",
    23: "RStick Down",
    24: "RStick Left",
    25: "RStick Right",
    26: "Shake",
    27: "Tilt Up",
    28: "Tilt Down",
    29: "Tilt Left",
    30: "Tilt Right",
    31: "Flick",
    32: "SL(L)",
    33: "SR(L)",
    34: "SL(R)",
    35: "SR(R)",
}

_BASE_KEY_TO_HOTSPOT: dict[int, str] = {
    1: "LSUp",
    2: "LSDown",
    3: "LSLeft",
    4: "LSRight",
    8: "A",
    9: "B",
    10: "X",
    11: "Y",
    12: "L",
    13: "R",
    14: "ZL",
    15: "ZR",
    16: "Plus",
    17: "Minus",
    18: "Home",
    19: "Capture",
    20: "LStick",
    21: "RStick",
    22: "RSUp",
    23: "RSDown",
    24: "RSLeft",
    25: "RSRight",
    26: "Shake",
    27: "TiltUp",
    28: "TiltDn",
    29: "TiltL",
    30: "TiltR",
    31: "Flick",
    32: "SL(L)",
    33: "SR(L)",
    34: "SL(R)",
    35: "SR(R)",
}

_ACTIVITY_CATEGORY_ORDER = ("input", "layer", "macro")
_ACTIVITY_LANE_LIMITS = {
    "input": 4,
    "layer": 2,
    "macro": 2,
}


def label_for_key_id(key_id: int) -> str:
    base_key_id = key_id % 128
    return _BASE_KEY_LABELS.get(base_key_id, f"key_{key_id}")


def device_index_for_key_id(key_id: int) -> int:
    return max(0, key_id // 128)


def hotspot_for_key_id(key_id: int) -> str | None:
    base_key_id = key_id % 128
    return _BASE_KEY_TO_HOTSPOT.get(base_key_id)


def display_label_for_key_id(key_id: int) -> str:
    label = label_for_key_id(key_id)
    device_index = device_index_for_key_id(key_id)
    if device_index == 0:
        return label
    return f"{label} [D{device_index}]"


def describe_rssi(rssi: int | None) -> str:
    if rssi is None:
        return "—"
    if rssi >= -55:
        quality = "Excellent"
    elif rssi >= -67:
        quality = "Strong"
    elif rssi >= -75:
        quality = "Fair"
    else:
        quality = "Weak"
    return f"{rssi} dBm ({quality})"


def describe_mapped_key_activity(key_id: int, pressed: bool) -> str:
    action = "pressed" if pressed else "released"
    return f"{display_label_for_key_id(key_id)} {action}"


def describe_layer_activity(name: str, active: bool) -> str:
    return f"Layer {name} {'enabled' if active else 'disabled'}"


def describe_macro_activity(macro_id: str, state: str) -> str:
    return f"Macro {macro_id} {state}"


def activity_decay_amount(age_index: int) -> float:
    if age_index <= 0:
        return 0.0
    return min(0.12 * age_index, 0.60)


def activity_category_title(category: str) -> str:
    return {
        "input": "Inputs",
        "layer": "Layers",
        "macro": "Macros",
    }.get(category, category.title())


def group_recent_activity(entries: list[tuple[str, str]]) -> list[tuple[str, list[str]]]:
    grouped: dict[str, list[str]] = {category: [] for category in _ACTIVITY_CATEGORY_ORDER}
    extras: dict[str, list[str]] = {}
    for category, label in entries:
        if category in grouped:
            grouped[category].append(label)
        else:
            extras.setdefault(category, []).append(label)

    sections: list[tuple[str, list[str]]] = [
        (category, labels) for category, labels in grouped.items() if labels
    ]
    sections.extend((category, labels) for category, labels in extras.items() if labels)
    return sections


def compact_recent_activity_groups(
    groups: list[tuple[str, list[str]]],
) -> list[tuple[str, list[str], int]]:
    compacted: list[tuple[str, list[str], int]] = []
    for category, labels in groups:
        limit = _ACTIVITY_LANE_LIMITS.get(category, 2)
        visible_labels = labels[:limit]
        overflow_count = max(0, len(labels) - len(visible_labels))
        compacted.append((category, visible_labels, overflow_count))
    return compacted


def overflow_summary_label(count: int) -> str:
    return f"+{count} older"


def build_active_controls_summary(key_ids: set[int]) -> str:
    if not key_ids:
        return "—"

    grouped: dict[int, list[str]] = {}
    for key_id in sorted(key_ids, key=lambda value: (device_index_for_key_id(value), label_for_key_id(value))):
        grouped.setdefault(device_index_for_key_id(key_id), []).append(label_for_key_id(key_id))

    if len(grouped) == 1 and 0 in grouped:
        return ", ".join(grouped[0])

    sections = [f"D{device_index}: {', '.join(labels)}" for device_index, labels in grouped.items()]
    return " | ".join(sections)
