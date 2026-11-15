# Builds the data for each widget. Each source is fetched once per request and only if needed,
# and a failing source only takes down its own widgets.

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from .google import GoogleCalendar
from .sources import Announcement, Assignment, D3l, Event, SourceError, Weather, day_bounds
from .store import Person, WidgetPlacement

logger = logging.getLogger(__name__)

CALENDAR_DAYS = 7  # today and the next six days
ASSIGNMENTS_SHOWN = 8
ANNOUNCEMENTS_SINCE = timedelta(days=14)
ANNOUNCEMENTS_SHOWN = 8
SOON = timedelta(days=3)  # the summary mentions work due this soon
NEW = timedelta(days=2)  # and announcements this new

# what each widget reads (clock needs nothing)
NEEDS = {
    "greeting": set(),
    "weather": {"weather"},
    "calendar": {"events", "google"},
    "assignments": {"assignments"},
    "announcements": {"announcements"},
    "summary": {"weather", "events", "google", "assignments", "announcements"},
}


def first_name(person: Person) -> str:
    return person.name.split()[0]


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(word.title() for word in rest)


def _jsonable(items: list) -> list[dict[str, Any]]:
    """Dataclasses as JSON: camelCase keys (all_day -> allDay), dates as ISO strings."""
    return [{_camel(k): v.isoformat() if isinstance(v, datetime) else v for k, v in asdict(i).items()} for i in items]


def _time(moment: datetime, zone: ZoneInfo) -> str:
    return moment.astimezone(zone).strftime("%-I:%M %p")


def summarize(events: Optional[list[Event]], assignments: Optional[list[Assignment]],
              weather: Optional[dict[str, Any]], now: datetime,
              announcements: Optional[list[Announcement]] = None) -> str:
    """A couple of sentences about the day, skipping whatever couldn't be fetched."""
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
        unit = weather["units"]["temperature"]  # "F" or "C"
        today = weather["today"]
        parts.append(
            f"{weather['current']['description']}, high of {round(today['high'])}\u00b0{unit}"
            + (f", {round(today['precipitationChance'])}% chance of rain." if today["precipitationChance"] >= 30 else ".")
        )

    return " ".join(parts)


async def build(person: Person, placements: list[WidgetPlacement], d3l: D3l, weather: Weather,
                google: GoogleCalendar, zone: ZoneInfo, units: str = "imperial") -> list[dict[str, Any]]:
    now = datetime.now(zone)
    needed = set().union(*(NEEDS.get(p.key, set()) for p in placements))
    start, end = day_bounds(now, CALENDAR_DAYS)

    brightspace = d3l.for_person(person.id)
    fetchers: dict[str, Callable[[], Awaitable[Any]]] = {
        "weather": lambda: weather.get(units),
        "events": lambda: brightspace.events(start, end),
        "google": lambda: google.events(person.id, start, end),
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
            if name == "google":   # the calendar still shows Brightspace, so this would go unnoticed
                logger.warning("Google Calendar for person %d: %s", person.id, result.message)
        elif isinstance(result, Exception):
            # something unexpected, e.g. an oddly shaped Brightspace item: only this source's widgets go without
            logger.error("Reading %s for person %d failed unexpectedly", name, person.id, exc_info=result)
            errors[name] = SourceError("unavailable", f"Couldn't read {name}")
        elif isinstance(result, BaseException):
            raise result
        else:
            got[name] = result

    # Brightspace and Google events in one list. Either can be missing (not connected, or down),
    # and the calendar shows whatever there is.
    lists = [got[name] for name in ("events", "google") if got.get(name) is not None]
    events = sorted((e for found in lists for e in found), key=lambda e: e.starts) if lists else None

    def data_for(key: str) -> Any:
        if key == "greeting":
            return {"name": first_name(person)}
        if key == "weather":
            return got["weather"]
        if key == "calendar":
            return {"events": _jsonable(events)}
        if key == "assignments":
            return {"assignments": _jsonable(got["assignments"][:ASSIGNMENTS_SHOWN])}
        if key == "announcements":
            return {"announcements": _jsonable(got["announcements"][:ANNOUNCEMENTS_SHOWN])}
        if key == "summary":
            return {"text": summarize(events, got.get("assignments"), got.get("weather"), now,
                                      got.get("announcements"))}
        return None

    widgets = []
    for p in placements:
        # summary works with whatever it has, the others need all their sources
        failed = [errors[s] for s in NEEDS.get(p.key, set()) if s in errors]
        error = failed[0] if failed and p.key != "summary" else None
        if p.key == "calendar":
            error = None if events is not None else errors.get("events") or errors.get("google")
        widgets.append({
            "key": p.key, "name": p.name, "x": p.x, "y": p.y, "w": p.w, "h": p.h,
            "settings": p.settings,
            "data": None if error else data_for(p.key),
            "error": {"code": error.code, "message": error.message} if error else None,
        })
    return widgets
