# settings come from env vars (see .env.example)

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # where the mirror is
    latitude: float
    longitude: float
    label: str = ""
    # seconds
    forecast_ttl: float = 600
    alerts_ttl: float = 120
    # pause after a failed fetch (old data is served meanwhile)
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
