# settings come from env vars (see .env.example)

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional
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
    # d3l's SERVICE_API_KEY
    d3l_service_key: str
    weather_url: str
    faces_url: str
    faces_api_key: str
    # for deciding what "today" is
    timezone: ZoneInfo
    # blink cutoffs on the 0-1 eye score from faces: open at/above the first, closed at/below the second
    eyes_open_at: float = 0.7
    eyes_closed_at: float = 0.45
    # Google Calendar: the app's OAuth client and the key its saved tokens are encrypted with.
    # leave them out and the calendar just shows Brightspace
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_token_key: Optional[str] = None


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
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID") or None,
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET") or None,
        google_token_key=os.environ.get("GOOGLE_TOKEN_KEY") or None,
    )
