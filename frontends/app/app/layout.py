import math


VARIANTS = {
    "clock": ("full", "time"),
    "greeting": ("greeting", "name"),
    "weather": ("compact", "current", "hourly"),
    "calendar": ("comfortable", "compact"),
    "assignments": ("comfortable", "compact"),
    "announcements": ("detailed", "headlines"),
}

DEFAULT_VARIANT = {
    "clock": "full",
    "greeting": "greeting",
    "weather": "current",
    "calendar": "comfortable",
    "assignments": "comfortable",
    "announcements": "detailed",
}


class LayoutError(ValueError):
    pass


def validate_layout(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("widgets"), list):
        raise LayoutError("widgets must be a list")
    if len(payload["widgets"]) > 100:
        raise LayoutError("too many widgets")

    result = []
    seen = set()
    for item in payload["widgets"]:
        key = item.get("key") if isinstance(item, dict) else None
        if not isinstance(key, str) or not key:
            raise LayoutError("each widget needs a key")
        if key in seen:
            raise LayoutError("duplicate widget")
        if not isinstance(item.get("enabled"), bool):
            raise LayoutError("enabled must be true or false")

        values = []
        for field in ("x", "y", "w", "h"):
            value = item.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise LayoutError(f"{field} must be a number")
            values.append(float(value))
        x, y, width, height = values
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise LayoutError("widget must fit on the screen")

        allowed = VARIANTS.get(key, ("default",))
        variant = item.get("variant", DEFAULT_VARIANT.get(key, "default"))
        if variant not in allowed:
            raise LayoutError(f"unknown {key} variant")

        seen.add(key)
        result.append({"key": key, "enabled": item["enabled"], "x": x, "y": y,
                       "w": width, "h": height, "variant": variant})
    return result
