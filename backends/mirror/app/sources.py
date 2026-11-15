"""
Fetching widget data from the other backends: d3l (Brightspace) and weather.
Brightspace's raw data is trimmed down to what the mirror shows.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx


class SourceError(Exception):
    """A backend couldn't provide data. `code` tells the mirror what to show instead."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Event:
    title: str
    course: Optional[str]
    starts: datetime
    ends: datetime
    all_day: bool
    location: Optional[str]


@dataclass(frozen=True)
class Assignment:
    name: str
    course: Optional[str]
    due: datetime
    overdue: bool


@dataclass(frozen=True)
class Announcement:
    title: str
    course: Optional[str]
    posted: datetime
    text: str   # plain text, one line, shortened


# Announcements are per course, so a person with many courses means many requests.
ANNOUNCEMENT_REQUESTS_AT_ONCE = 8


# Marist names courses like "CMPT_435L_112_26F ALGORITHM ANALYSISDESIGN": subject, number,
# section, term, then a truncated title. The mirror shows just "CMPT 435L".
_SECTION_NAME = re.compile(r"^([A-Z]{2,5})_(\w+?)_\w+?_\w+\b")


def course_name(name: Optional[str]) -> Optional[str]:
    """A short course name for the mirror. Names in other formats are left as they are."""
    if not name:
        return None
    match = _SECTION_NAME.match(name)
    return f"{match[1]} {match[2]}" if match else name


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _brightspace_time(moment: datetime) -> str:
    """Brightspace wants UTC with milliseconds, e.g. 2026-11-14T05:00:00.000Z."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class D3l:
    """d3l, called with the service key on behalf of one person."""

    def __init__(self, client: httpx.AsyncClient, base_url: str, service_key: str):
        self._client = client
        self._base_url = base_url
        self._service_key = service_key

    async def get(self, person_id: int, path: str, params: Optional[dict[str, str]] = None) -> Any:
        try:
            response = await self._client.get(
                f"{self._base_url}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._service_key}", "X-Person-Id": str(person_id)},
            )
        except httpx.HTTPError as error:
            raise SourceError("brightspace_unavailable", f"Couldn't reach d3l: {error!r}") from error
        if response.status_code == 401 and _code(response) == "signin_required":
            raise SourceError("signin_required", "Connect Brightspace in the app to see this")
        if response.is_error:
            raise SourceError("brightspace_unavailable", f"d3l {path} returned {response.status_code}")
        return response.json()

    def for_person(self, person_id: int) -> "Brightspace":
        return Brightspace(self, person_id)


class Brightspace:
    """
    One person's Brightspace data, for one mirror request. The course list is needed by
    several widgets, so it's fetched once and shared.
    """

    def __init__(self, d3l: D3l, person_id: int):
        self._d3l = d3l
        self._person_id = person_id
        self._courses: Optional[asyncio.Task] = None

    def _get(self, path: str, params: Optional[dict[str, str]] = None) -> Any:
        return self._d3l.get(self._person_id, path, params)

    async def courses(self) -> list[dict]:
        if self._courses is None:
            self._courses = asyncio.ensure_future(self._get("/courses"))
        return await self._courses

    async def _course_names(self) -> dict[int, Optional[str]]:
        return {int(c["OrgUnit"]["Id"]): course_name(c["OrgUnit"]["Name"]) for c in await self.courses()}

    async def events(self, start: datetime, end: datetime) -> list[Event]:
        """Calendar events overlapping [start, end) that haven't finished yet."""
        raw = await self._get("/calendar", {
            "startDateTime": _brightspace_time(start),
            "endDateTime": _brightspace_time(end),
        })
        now = datetime.now(timezone.utc)
        events = [
            Event(
                title=e["Title"],
                course=course_name(e.get("OrgUnitName")),
                starts=_utc(e["StartDateTime"]),
                ends=_utc(e["EndDateTime"]),
                all_day=bool(e.get("IsAllDayEvent")),
                location=e.get("LocationName") or None,
            )
            for e in raw
        ]
        return sorted((e for e in events if e.ends >= now), key=lambda e: e.starts)

    async def assignments(self) -> list[Assignment]:
        """Overdue work, then upcoming unfinished work, soonest first."""
        due, overdue, courses = await asyncio.gather(
            self._get("/due"),
            self._get("/overdue"),
            self._course_names(),
        )
        now = datetime.now(timezone.utc)

        def course(item: dict) -> Optional[str]:
            return courses.get(int(item["OrgUnitId"]))

        late = [
            Assignment(i["ItemName"], course(i), _utc(i["DueDate"]), overdue=True)
            for i in overdue if i.get("DueDate")
        ]
        # /due also returns past and finished work, so keep only what's still ahead and open.
        upcoming = [
            Assignment(i["ItemName"], course(i), _utc(i["DueDate"]), overdue=False)
            for i in due
            if i.get("DueDate") and not i.get("DateCompleted") and not i.get("IsExempt")
            and _utc(i["DueDate"]) >= now
        ]
        return sorted(late, key=lambda a: a.due) + sorted(upcoming, key=lambda a: a.due)

    async def announcements(self, since: datetime) -> list[Announcement]:
        """Announcements posted since `since` in any active course, newest first."""
        active = [c for c in await self.courses() if c["Access"].get("IsActive") and c["Access"].get("CanAccess")]
        limit = asyncio.Semaphore(ANNOUNCEMENT_REQUESTS_AT_ONCE)
        now = datetime.now(timezone.utc)

        async def from_course(course: dict) -> list[Announcement]:
            async with limit:
                try:
                    items = await self._get(f"/courses/{int(course['OrgUnit']['Id'])}/announcements")
                except SourceError as error:
                    if error.code == "signin_required":
                        raise
                    return []  # Brightspace refuses (403) courses whose access has ended
            found = []
            for item in items:
                posted = item.get("StartDate") or item.get("CreatedDate")
                if item.get("IsHidden") or item.get("IsPublished") is False or not posted:
                    continue
                posted_at = _utc(posted)
                if since <= posted_at <= now:
                    found.append(Announcement(
                        title=item["Title"],
                        course=course_name(course["OrgUnit"]["Name"]),
                        posted=posted_at,
                        text=_snippet((item.get("Body") or {}).get("Text") or ""),
                    ))
            return found

        per_course = await asyncio.gather(*(from_course(c) for c in active))
        found = sorted((a for items in per_course for a in items), key=lambda a: a.posted, reverse=True)

        # The same announcement is often posted to several courses: show it once, listing each course.
        merged: dict[tuple[str, str], Announcement] = {}
        for item in found:
            key = (item.title, item.text)
            first = merged.get(key)
            if first is None:
                merged[key] = item
            elif item.course and item.course not in (first.course or "").split(", "):
                merged[key] = replace(first, course=", ".join(filter(None, [first.course, item.course])))
        return list(merged.values())


def _snippet(text: str, limit: int = 280) -> str:
    """Body text on one line, cut at a word boundary."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit].rsplit(" ", 1)[0] + "…"


class Weather:
    def __init__(self, client: httpx.AsyncClient, base_url: str):
        self._client = client
        self._base_url = base_url

    async def get(self, units: str) -> dict[str, Any]:
        try:
            response = await self._client.get(f"{self._base_url}/weather", params={"units": units})
        except httpx.HTTPError as error:
            raise SourceError("weather_unavailable", f"Couldn't reach weather: {error!r}") from error
        if response.is_error:
            raise SourceError("weather_unavailable", "Weather is unavailable right now")
        return response.json()


@dataclass(frozen=True)
class Identified:
    faces: int                     # how many faces were in the picture
    person_id: Optional[int]       # who it is, if recognized
    eyes_open: Optional[float]     # how open their eyes are, 0-1 (None if no face is close enough)


class Faces:
    """The faces service: works out who's in a camera frame."""

    def __init__(self, client: httpx.AsyncClient, base_url: str, api_key: str):
        self._client = client
        self._base_url = base_url
        self._api_key = api_key

    async def identify(self, image: bytes, content_type: str) -> Identified:
        try:
            response = await self._client.post(
                f"{self._base_url}/identify",
                content=image,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": content_type},
            )
        except httpx.HTTPError as error:
            raise SourceError("faces_unavailable", f"Couldn't reach the faces service: {error!r}") from error
        if response.status_code == 400:
            raise SourceError("bad_image", "That isn't a readable image")
        if response.is_error:
            raise SourceError("faces_unavailable", f"Faces service returned {response.status_code}")
        body = response.json()
        return Identified(body["faces"], body["match"]["personId"] if body["match"] else None, body["eyesOpen"])


def _code(response: httpx.Response) -> Optional[str]:
    try:
        return response.json().get("code")
    except ValueError:
        return None


def day_bounds(now: datetime, days: int) -> tuple[datetime, datetime]:
    """Midnight today (in `now`'s timezone) to midnight `days` days later."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=days)
