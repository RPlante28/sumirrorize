"""Settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set (see .env.example)")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    d3l_url: str
    # d3l's SERVICE_API_KEY: lets this backend read any person's Brightspace data.
    d3l_service_key: str
    weather_url: str
    faces_url: str
    faces_api_key: str
    # Where the mirror is, for deciding what "today" means.
    timezone: ZoneInfo
    # The blink check (see blink.py). The faces service scores how open someone's eyes are from
    # 0 to 1: they count as open at or above the first number and closed at or below the second.
    eyes_open_at: float = 0.7
    eyes_closed_at: float = 0.45


def load_settings() -> Settings:
    return Settings(
        database_url=_required("DATABASE_URL"),
        d3l_url=_required("D3L_URL").rstrip("/"),
        d3l_service_key=_required("D3L_SERVICE_KEY"),
        weather_url=_required("WEATHER_URL").rstrip("/"),
        faces_url=_required("FACES_URL").rstrip("/"),
        faces_api_key=_required("FACES_API_KEY"),
        timezone=ZoneInfo(os.environ.get("MIRROR_TIMEZONE", "America/New_York")),
        eyes_open_at=float(os.environ.get("MIRROR_EYES_OPEN_AT", "0.7")),
        eyes_closed_at=float(os.environ.get("MIRROR_EYES_CLOSED_AT", "0.45")),
    )
