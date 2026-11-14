"""Settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Where the mirror is. Weather is for the mirror's spot, not each person's.
    latitude: float
    longitude: float
    label: str = ""
    # How long fetched data counts as fresh, in seconds.
    forecast_ttl: float = 600
    alerts_ttl: float = 120
    # After a failed fetch, wait this long before trying again (old data is served meanwhile).
    retry_after: float = 30


def _coordinate(name: str, limit: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        raise RuntimeError(f"{name} must be set (see .env.example)")
    value = float(raw)
    if not -limit <= value <= limit:
        raise RuntimeError(f"{name} must be between -{limit} and {limit}")
    return value


def load_settings() -> Settings:
    return Settings(
        latitude=_coordinate("WEATHER_LATITUDE", 90),
        longitude=_coordinate("WEATHER_LONGITUDE", 180),
        label=os.environ.get("WEATHER_LABEL", ""),
    )
