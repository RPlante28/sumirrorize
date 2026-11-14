"""
Builds the data for each of a person's widgets. Every source is fetched at most once per
request, only if a widget needs it, and a failing source only affects its own widgets.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from .sources import Announcement, Assignment, D3l, Event, SourceError, Weather, day_bounds
from .store import Person, WidgetPlacement

CALENDAR_DAYS = 7          # the calendar shows today and the next six days
ASSIGNMENTS_SHOWN = 8
ANNOUNCEMENTS_SINCE = timedelta(days=14)
ANNOUNCEMENTS_SHOWN = 8
SOON = timedelta(days=3)   # the summary mentions work due within this long
NEW = timedelta(days=2)    # the summary mentions announcements posted within this long

# Which sources each widget reads. Widgets not listed here (clock) need nothing.
NEEDS = {
    "greeting": set(),
    "weather": {"weather"},
    "calendar": {"events"},
    "assignments": {"assignments"},
    "announcements": {"announcements"},
    "summary": {"weather", "events", "assignments", "announcements"},
}


def first_name(person: Person) -> str:
    return person.name.split()[0]


def _jsonable(items: list) -> list[dict[str, Any]]:
    return [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in asdict(i).items()} for i in items]


def _time(moment: datetime, zone: ZoneInfo) -> str:
    return moment.astimezone(zone).strftime("%-I:%M %p")


def summarize(events: Optional[list[Event]], assignments: Optional[list[Assignment]],
              weather: Optional[dict[str, Any]], now: datetime,
              announcements: Optional[list[Announcement]] = None) -> str:
    """A couple of plain sentences about the day. Skips anything that couldn't be fetched."""
    zone = now.tzinfo
    parts: list[str] = []

    if events is not None:
        today = [e for e in events if e.starts.astimezone(zone).date() == now.date() or e.starts <= now]
        if not today:
            parts.append("Nothing on your calendar today.")
        else:
            nxt = next((e for e in today if e.starts > now), None)
            count = f"{len(today)} event{'s' if len(today) != 1 else ''} today"
            parts.append(f"{count}, next up {nxt.title} at {_time(nxt.starts, zone)}." if nxt else f"{count}.")

    if assignments is not None:
        overdue = sum(a.overdue for a in assignments)
        soon = sum(not a.overdue and a.due - now <= SOON for a in assignments)
        plural = lambda n: "assignment" if n == 1 else "assignments"  # noqa: E731
        if soon and overdue:
            parts.append(f"{soon} {plural(soon)} due in the next 3 days, {overdue} overdue.")
        elif soon:
            parts.append(f"{soon} {plural(soon)} due in the next 3 days.")
        elif overdue:
            parts.append(f"{overdue} {plural(overdue)} overdue.")
        else:
            parts.append("No assignments due in the next 3 days.")

    if announcements:
        new = sum(now - a.posted <= NEW for a in announcements)
        if new:
            parts.append(f"{new} new announcement{'s' if new != 1 else ''} since yesterday.")

    if weather is not None:
        unit = weather["units"]["temperature"][-1]  # "F" or "C"
        today = weather["today"]
        parts.append(
            f"{weather['current']['description']}, high of {round(today['high'])}°{unit}"
            + (f", {round(today['precipitationChance'])}% chance of rain." if today["precipitationChance"] >= 30 else ".")
        )

    return " ".join(parts)


async def build(person: Person, placements: list[WidgetPlacement], d3l: D3l, weather: Weather,
                zone: ZoneInfo) -> list[dict[str, Any]]:
    now = datetime.now(zone)
    needed = set().union(*(NEEDS.get(p.key, set()) for p in placements))

    # Weather follows the person's units setting on their weather widget.
    weather_settings = next((p.settings for p in placements if p.key == "weather"), {})
    units = weather_settings.get("units", "imperial")
    start, end = day_bounds(now, CALENDAR_DAYS)

    brightspace = d3l.for_person(person.id)
    fetchers: dict[str, Callable[[], Awaitable[Any]]] = {
        "weather": lambda: weather.get(units),
        "events": lambda: brightspace.events(start, end),
        "assignments": lambda: brightspace.assignments(),
        "announcements": lambda: brightspace.announcements(now - ANNOUNCEMENTS_SINCE),
    }
    names = sorted(needed)
    results = await asyncio.gather(*(fetchers[n]() for n in names), return_exceptions=True)
    got: dict[str, Any] = {}
    errors: dict[str, SourceError] = {}
    for name, result in zip(names, results):
        if isinstance(result, SourceError):
            errors[name] = result
        elif isinstance(result, BaseException):
            raise result
        else:
            got[name] = result

    def data_for(key: str) -> Any:
        if key == "greeting":
            return {"name": first_name(person)}
        if key == "weather":
            return got["weather"]
        if key == "calendar":
            return {"events": _jsonable(got["events"])}
        if key == "assignments":
            return {"assignments": _jsonable(got["assignments"][:ASSIGNMENTS_SHOWN])}
        if key == "announcements":
            return {"announcements": _jsonable(got["announcements"][:ANNOUNCEMENTS_SHOWN])}
        if key == "summary":
            return {"text": summarize(got.get("events"), got.get("assignments"), got.get("weather"), now,
                                      got.get("announcements"))}
        return None

    widgets = []
    for p in placements:
        # Summary works with whatever it has; other widgets need all their sources.
        failed = [errors[s] for s in NEEDS.get(p.key, set()) if s in errors]
        error = failed[0] if failed and p.key != "summary" else None
        widgets.append({
            "key": p.key, "name": p.name, "x": p.x, "y": p.y, "w": p.w, "h": p.h,
            "settings": p.settings,
            "data": None if error else data_for(p.key),
            "error": {"code": error.code, "message": error.message} if error else None,
        })
    return widgets
