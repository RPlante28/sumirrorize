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
    # What the mirror page must send. Everything here is personal data, and the page is public.
    mirror_key: str
    # Where the mirror is, for deciding what "today" means.
    timezone: ZoneInfo


def load_settings() -> Settings:
    mirror_key = _required("MIRROR_KEY")
    if len(mirror_key) < 32:
        raise RuntimeError("MIRROR_KEY must be at least 32 characters")
    return Settings(
        database_url=_required("DATABASE_URL"),
        d3l_url=_required("D3L_URL").rstrip("/"),
        d3l_service_key=_required("D3L_SERVICE_KEY"),
        weather_url=_required("WEATHER_URL").rstrip("/"),
        mirror_key=mirror_key,
        timezone=ZoneInfo(os.environ.get("MIRROR_TIMEZONE", "America/New_York")),
    )
