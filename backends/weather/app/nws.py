"""
Active weather alerts from the National Weather Service (US only).
Free, no API key. Docs: https://www.weather.gov/documentation/services-web-api

Adapted from StormWatch's api/nws.py, minus the storm polygons and distance math.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

URL = "https://api.weather.gov/alerts/active"

# Most serious first.
_SEVERITY = {"Extreme": 4, "Severe": 3, "Moderate": 2, "Minor": 1}
_URGENCY = {"Immediate": 3, "Expected": 2, "Future": 1, "Past": 0}


@dataclass(frozen=True)
class Alert:
    event: str            # e.g. "Winter Storm Warning"
    headline: str
    severity: str         # "Extreme" | "Severe" | "Moderate" | "Minor" | "Unknown"
    urgency: str
    area: str
    starts: Optional[datetime]
    ends: Optional[datetime]
    description: str
    instruction: str


def _time(text: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(text) if text else None


async def fetch_alerts(client: httpx.AsyncClient, latitude: float, longitude: float) -> list[Alert]:
    response = await client.get(
        URL,
        params={"point": f"{latitude:.4f},{longitude:.4f}", "status": "actual"},
        headers={"Accept": "application/geo+json"},
    )
    response.raise_for_status()

    alerts = []
    for feature in response.json().get("features", []):
        p = feature.get("properties") or {}
        alerts.append(Alert(
            event=p.get("event") or "Weather alert",
            headline=p.get("headline") or "",
            severity=p.get("severity") or "Unknown",
            urgency=p.get("urgency") or "Unknown",
            area=p.get("areaDesc") or "",
            starts=_time(p.get("onset") or p.get("effective")),
            # "ends" is when the weather ends; "expires" is when this message does.
            ends=_time(p.get("ends") or p.get("expires")),
            description=p.get("description") or "",
            instruction=p.get("instruction") or "",
        ))

    alerts.sort(key=lambda a: (_SEVERITY.get(a.severity, 0), _URGENCY.get(a.urgency, 0)), reverse=True)
    return alerts
