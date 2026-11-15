# data is fetched in metric and converted per request

from __future__ import annotations

from enum import Enum


class Units(str, Enum):
    imperial = "imperial"
    metric = "metric"


LABELS = {
    Units.imperial: {"temperature": "F", "speed": "mph"},
    Units.metric: {"temperature": "C", "speed": "km/h"},
}

_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def temperature(celsius: float, units: Units) -> float:
    value = celsius * 9 / 5 + 32 if units is Units.imperial else celsius
    return round(value, 1)


def speed(kmh: float, units: Units) -> float:
    value = kmh * 0.621371 if units is Units.imperial else kmh
    return round(value, 1)


def compass(degrees: float) -> str:
    """Wind direction as a compass point, e.g. 315 -> "NW"."""
    return _COMPASS[round(degrees / 22.5) % 16]
