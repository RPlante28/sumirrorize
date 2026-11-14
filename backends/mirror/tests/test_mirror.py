"""Runs the mirror backend against a fake database and fake d3l/weather services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.sources import Assignment, Event, course_name
from app.store import Person, WidgetPlacement
from app.widgets import summarize

ZONE = ZoneInfo("America/New_York")
KEY = "mirror-key-0123456789abcdef0123456789"
SETTINGS = Settings(
    database_url="unused", d3l_url="http://d3l", d3l_service_key="service-key",
    weather_url="http://weather", mirror_key=KEY, timezone=ZONE,
)
NOW = datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def course(id: int, name: str, active: bool = True) -> dict:
    return {"OrgUnit": {"Id": id, "Name": name}, "Access": {"IsActive": active, "CanAccess": True}}


def news(title: str, posted: datetime, body: str = "Body.", **extra) -> dict:
    return {"Title": title, "StartDate": iso(posted), "CreatedDate": iso(posted), "IsHidden": False,
            "IsPublished": True, "Body": {"Text": body, "Html": f"<p>{body}</p>"}, **extra}


def placement(key: str, settings: Optional[dict] = None) -> WidgetPlacement:
    return WidgetPlacement(key, key.title(), 0.1, 0.1, 0.3, 0.2, settings or {})


class FakeStore:
    def __init__(self, widgets: list[WidgetPlacement]):
        self.widgets = widgets

    async def people(self):
        return [Person(3, "Alex Smith"), Person(4, "Riley Jones")]

    async def person(self, person_id):
        return {3: Person(3, "Alex Smith"), 4: Person(4, "Riley Jones")}.get(person_id)

    async def enabled_widgets(self, person_id):
        return self.widgets


WEATHER = {
    "units": {"temperature": "°F", "speed": "mph"},
    "current": {"description": "Overcast", "temperature": 41.7},
    "today": {"high": 44.4, "low": 34.9, "precipitationChance": 40},
}


class FakeBackends:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.signed_in = True
        self.weather_up = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "weather":
            if not self.weather_up:
                return httpx.Response(503, json={"error": "down", "code": "weather_unavailable"})
            return httpx.Response(200, json={**WEATHER, "units": {"temperature": "°C" if request.url.params["units"] == "metric" else "°F", "speed": "x"}})

        assert request.headers["authorization"] == "Bearer service-key"
        assert request.headers["x-person-id"] == "3"
        if not self.signed_in:
            return httpx.Response(401, json={"error": "sign in", "code": "signin_required"})
        if path == "/courses":
            return httpx.Response(200, json=[
                course(10, "Software Development"),
                course(11, "CMPT_435L_112_26F ALGORITHM ANALYSISDESIGN"),
                course(12, "Old course"),                # Brightspace answers 403
                course(13, "Inactive", active=False),    # never asked
            ])
        if path == "/courses/10/announcements":
            return httpx.Response(200, json=[
                news("Room change", NOW - timedelta(hours=5), body="Class is in\r\n  HC 2023  today."),
                news("Hidden", NOW - timedelta(hours=1), IsHidden=True),
                news("Draft", NOW - timedelta(hours=1), IsPublished=False),
                news("Ancient", NOW - timedelta(days=40)),
                news("Scheduled", NOW + timedelta(days=1)),
            ])
        if path == "/courses/11/announcements":
            return httpx.Response(200, json=[
                news("Exam moved", NOW - timedelta(days=4), body="word " * 100),
                news("Room change", NOW - timedelta(hours=6), body="Class is in HC 2023 today."),  # cross-posted
            ])
        if path == "/courses/12/announcements":
            return httpx.Response(403, json={"error": "ended", "code": "brightspace_error"})
        if path == "/due":
            return httpx.Response(200, json=[
                {"OrgUnitId": "10", "ItemName": "Old, done", "DueDate": iso(NOW - timedelta(days=30)), "DateCompleted": iso(NOW), "IsExempt": False},
                {"OrgUnitId": "10", "ItemName": "Old, not done", "DueDate": iso(NOW - timedelta(days=30)), "DateCompleted": None, "IsExempt": False},
                {"OrgUnitId": "10", "ItemName": "Later", "DueDate": iso(NOW + timedelta(days=6)), "DateCompleted": None, "IsExempt": False},
                {"OrgUnitId": "10", "ItemName": "Soon", "DueDate": iso(NOW + timedelta(days=1)), "DateCompleted": None, "IsExempt": False},
                {"OrgUnitId": "10", "ItemName": "Done early", "DueDate": iso(NOW + timedelta(days=2)), "DateCompleted": iso(NOW), "IsExempt": False},
                {"OrgUnitId": "10", "ItemName": "Exempt", "DueDate": iso(NOW + timedelta(days=2)), "DateCompleted": None, "IsExempt": True},
            ])
        if path == "/overdue":
            return httpx.Response(200, json=[{"OrgUnitId": 99, "ItemName": "Late lab", "DueDate": iso(NOW - timedelta(days=2))}])
        if path == "/calendar":
            assert request.url.params["startDateTime"].endswith(".000Z")
            return httpx.Response(200, json=[
                {"Title": "Finished", "OrgUnitName": "Algorithms", "StartDateTime": iso(NOW - timedelta(hours=3)),
                 "EndDateTime": iso(NOW - timedelta(hours=2)), "IsAllDayEvent": False, "LocationName": ""},
                {"Title": "Quiz 3", "OrgUnitName": "Algorithms", "StartDateTime": iso(NOW + timedelta(days=2)),
                 "EndDateTime": iso(NOW + timedelta(days=2, hours=1)), "IsAllDayEvent": False, "LocationName": "HC 2023"},
            ])
        return httpx.Response(404, json={"error": "no", "code": "x"})


@pytest.fixture
def backends() -> FakeBackends:
    return FakeBackends()


def client_for(backends: FakeBackends, widgets: list[WidgetPlacement]) -> TestClient:
    app = create_app(SETTINGS, store=FakeStore(widgets), transport=httpx.MockTransport(backends))
    return TestClient(app, headers={"Authorization": f"Bearer {KEY}"})


ALL = [placement(k) for k in ("clock", "greeting", "weather", "calendar", "assignments", "announcements", "summary")]


def widget(body: dict, key: str) -> dict:
    return next(w for w in body["widgets"] if w["key"] == key)


def test_needs_mirror_key(backends):
    app = create_app(SETTINGS, store=FakeStore(ALL), transport=httpx.MockTransport(backends))
    with TestClient(app) as client:
        assert client.get("/api/people").status_code == 401
        wrong = client.get("/api/people/3/mirror", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401 and wrong.json()["code"] == "bad_mirror_key"


def test_people(backends):
    with client_for(backends, ALL) as client:
        assert client.get("/api/people").json() == [{"id": 3, "name": "Alex Smith"}, {"id": 4, "name": "Riley Jones"}]


def test_unknown_person(backends):
    with client_for(backends, ALL) as client:
        response = client.get("/api/people/99/mirror")
    assert response.status_code == 404 and response.json()["code"] == "no_such_person"


def test_full_mirror(backends):
    with client_for(backends, ALL) as client:
        body = client.get("/api/people/3/mirror").json()

    assert body["person"] == {"id": 3, "name": "Alex Smith"}
    assert [w["key"] for w in body["widgets"]] == ["clock", "greeting", "weather", "calendar", "assignments", "announcements", "summary"]
    assert widget(body, "clock")["data"] is None
    assert widget(body, "greeting")["data"] == {"name": "Alex"}
    assert widget(body, "weather")["data"]["current"]["description"] == "Overcast"
    assert widget(body, "clock")["x"] == 0.1

    events = widget(body, "calendar")["data"]["events"]
    assert [e["title"] for e in events] == ["Quiz 3"]  # finished event dropped
    assert events[0]["course"] == "Algorithms" and events[0]["location"] == "HC 2023"

    work = widget(body, "assignments")["data"]["assignments"]
    assert [(a["name"], a["overdue"]) for a in work] == [("Late lab", True), ("Soon", False), ("Later", False)]
    assert work[1]["course"] == "Software Development"
    assert work[0]["course"] is None  # course not in the list

    text = widget(body, "summary")["data"]["text"]
    assert "1 assignment due in the next 3 days, 1 overdue. 1 new announcement since yesterday." in text
    assert "Overcast, high of 44°F, 40% chance of rain." in text


def test_each_source_fetched_once(backends):
    with client_for(backends, ALL) as client:
        client.get("/api/people/3/mirror")
    paths = sorted(r.url.path for r in backends.requests)
    assert paths == ["/calendar", "/courses", "/courses/10/announcements", "/courses/11/announcements",
                     "/courses/12/announcements", "/due", "/overdue", "/weather"]


def test_only_needed_sources_fetched(backends):
    with client_for(backends, [placement("clock"), placement("weather")]) as client:
        client.get("/api/people/3/mirror")
    assert [r.url.host for r in backends.requests] == ["weather"]


def test_units_follow_weather_widget_setting(backends):
    with client_for(backends, [placement("weather", {"units": "metric"})]) as client:
        body = client.get("/api/people/3/mirror").json()
    assert backends.requests[0].url.params["units"] == "metric"
    assert widget(body, "weather")["data"]["units"]["temperature"] == "°C"


def test_not_signed_in_only_affects_brightspace_widgets(backends):
    backends.signed_in = False
    with client_for(backends, ALL) as client:
        body = client.get("/api/people/3/mirror").json()

    for key in ("calendar", "assignments", "announcements"):
        assert widget(body, key)["data"] is None
        assert widget(body, key)["error"]["code"] == "signin_required"
    assert widget(body, "weather")["error"] is None
    summary = widget(body, "summary")
    assert summary["error"] is None and summary["data"]["text"].startswith("Overcast")


def test_weather_down_only_affects_weather(backends):
    backends.weather_up = False
    with client_for(backends, ALL) as client:
        body = client.get("/api/people/3/mirror").json()
    assert widget(body, "weather")["error"]["code"] == "weather_unavailable"
    assert widget(body, "calendar")["error"] is None


def test_summary_wording():
    now = datetime(2026, 11, 14, 9, 0, tzinfo=ZONE)
    event = Event("CS lecture", "CS", now + timedelta(hours=2), now + timedelta(hours=3), False, None)
    text = summarize([event], [], None, now)
    assert text == "1 event today, next up CS lecture at 11:00 AM. No assignments due in the next 3 days."
    assert summarize([], [Assignment("x", None, now - timedelta(days=1), True)], None, now) == \
        "Nothing on your calendar today. 1 assignment overdue."
    assert summarize(None, None, None, now) == ""


def test_course_names_shortened():
    assert course_name("CMPT_435L_112_26F ALGORITHM ANALYSISDESIGN") == "CMPT 435L"
    assert course_name("MATH_310L_111_26F INT MATH REASON") == "MATH 310L"
    assert course_name("Software Development") == "Software Development"
    assert course_name("") is None


def test_announcements(backends):
    with client_for(backends, [placement("announcements")]) as client:
        body = client.get("/api/people/3/mirror").json()

    items = widget(body, "announcements")["data"]["announcements"]
    assert [a["title"] for a in items] == ["Room change", "Exam moved"]  # newest first
    assert items[0]["course"] == "Software Development, CMPT 435L"  # same post in two courses, shown once
    assert items[0]["text"] == "Class is in HC 2023 today."
    assert items[1]["course"] == "CMPT 435L"
    assert len(items[1]["text"]) <= 281 and items[1]["text"].endswith("…")
    assert not any("/courses/13/" in str(r.url) for r in backends.requests)
