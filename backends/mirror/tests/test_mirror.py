"""Runs the mirror backend against a fake database and fake d3l, weather and faces services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.passes import Passes
from app.sources import Assignment, Event, course_name
from app.store import Person, WidgetPlacement
from app.widgets import summarize

ZONE = ZoneInfo("America/New_York")
SETTINGS = Settings(
    database_url="unused", d3l_url="http://d3l", d3l_service_key="service-key",
    weather_url="http://weather", faces_url="http://faces", faces_api_key="faces-key", timezone=ZONE,
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
        self.face_requests: list[httpx.Request] = []
        self.signed_in = True
        self.weather_up = True
        self.faces_up = True

    def faces(self, request: httpx.Request) -> httpx.Response:
        """The 'frame' is a script: b"face:3" (person 3), b"stranger", b"nobody", b"broken"."""
        self.face_requests.append(request)
        assert request.headers["authorization"] == "Bearer faces-key"
        if not self.faces_up:
            return httpx.Response(503, json={"error": "down"})
        frame = request.content.decode()
        if frame == "broken":
            return httpx.Response(400, json={"error": "Not a readable image", "code": "bad_image"})
        if frame.startswith("face:"):
            return httpx.Response(200, json={"faces": 1, "match": {"personId": int(frame[5:]), "similarity": 0.9}})
        return httpx.Response(200, json={"faces": 0 if frame == "nobody" else 1, "match": None})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "faces":
            return self.faces(request)
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
    return TestClient(app)


def identify(client: TestClient, frame: str, content_type: str = "image/jpeg"):
    return client.post("/api/identify", content=frame.encode(), headers={"Content-Type": content_type})


def load_mirror(client: TestClient, frame: str = "face:3") -> dict:
    """What the mirror page does: recognize a face, then load that person's mirror with the pass."""
    token = identify(client, frame).json()["pass"]
    return client.get("/api/mirror", headers={"Authorization": f"Bearer {token}"}).json()


ALL = [placement(k) for k in ("clock", "greeting", "weather", "calendar", "assignments", "announcements", "summary")]


def widget(body: dict, key: str) -> dict:
    return next(w for w in body["widgets"] if w["key"] == key)


def test_recognized_face_gets_a_pass(backends):
    with client_for(backends, ALL) as client:
        body = identify(client, "face:3").json()
    assert body["faces"] == 1 and body["person"] == {"id": 3, "name": "Alex Smith"}
    assert body["pass"] and body["expiresAt"]
    assert backends.face_requests[0].headers["content-type"] == "image/jpeg"


def test_no_pass_for_strangers_or_empty_rooms(backends):
    with client_for(backends, ALL) as client:
        assert identify(client, "stranger").json() == {"faces": 1, "person": None, "pass": None, "expiresAt": None}
        assert identify(client, "nobody").json() == {"faces": 0, "person": None, "pass": None, "expiresAt": None}
        # Recognized, but that person has since been deleted.
        assert identify(client, "face:99").json()["pass"] is None


def test_mirror_needs_a_valid_pass(backends):
    with client_for(backends, ALL) as client:
        assert client.get("/api/mirror").json()["code"] == "pass_expired"
        token = identify(client, "face:3").json()["pass"]
        forged = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
        assert client.get("/api/mirror", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
        # The old ways in are gone.
        assert client.get("/api/people").status_code == 404
        assert client.get("/api/people/3/mirror").status_code == 404


def test_passes_expire_and_cant_be_moved():
    passes = Passes(lifetime_seconds=60, secret=b"s" * 32)
    token, _ = passes.issue(3)
    assert passes.check(token) == 3
    assert Passes(lifetime_seconds=-1, secret=b"s" * 32).check(Passes(-1, b"s" * 32).issue(3)[0]) is None
    assert Passes(60, secret=b"other" * 8).check(token) is None   # signed by a different server
    body, signature = token.split(".")
    other_body = Passes(60, b"x" * 32).issue(4)[0].split(".")[0]
    assert passes.check(f"{other_body}.{signature}") is None      # someone else's ID with this signature
    assert passes.check("garbage") is None


def test_bad_frames(backends):
    with client_for(backends, ALL) as client:
        assert identify(client, "face:3", "text/plain").json()["code"] == "bad_image"
        assert identify(client, "").json()["code"] == "too_large"
        assert identify(client, "broken").json()["code"] == "bad_image"
        backends.faces_up = False
        response = identify(client, "face:3")
        assert response.status_code == 503 and response.json()["code"] == "faces_unavailable"


def test_rate_limited(backends):
    with client_for(backends, ALL) as client:
        codes = [identify(client, "nobody").status_code for _ in range(12)]
    assert codes[:8] == [200] * 8 and 429 in codes[8:]


def test_full_mirror(backends):
    with client_for(backends, ALL) as client:
        body = load_mirror(client)

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
        load_mirror(client)
    paths = sorted(r.url.path for r in backends.requests)
    assert paths == ["/calendar", "/courses", "/courses/10/announcements", "/courses/11/announcements",
                     "/courses/12/announcements", "/due", "/overdue", "/weather"]


def test_only_needed_sources_fetched(backends):
    with client_for(backends, [placement("clock"), placement("weather")]) as client:
        load_mirror(client)
    assert [r.url.host for r in backends.requests] == ["weather"]


def test_units_follow_weather_widget_setting(backends):
    with client_for(backends, [placement("weather", {"units": "metric"})]) as client:
        body = load_mirror(client)
    assert backends.requests[0].url.params["units"] == "metric"
    assert widget(body, "weather")["data"]["units"]["temperature"] == "°C"


def test_not_signed_in_only_affects_brightspace_widgets(backends):
    backends.signed_in = False
    with client_for(backends, ALL) as client:
        body = load_mirror(client)

    for key in ("calendar", "assignments", "announcements"):
        assert widget(body, key)["data"] is None
        assert widget(body, key)["error"]["code"] == "signin_required"
    assert widget(body, "weather")["error"] is None
    summary = widget(body, "summary")
    assert summary["error"] is None and summary["data"]["text"].startswith("Overcast")


def test_weather_down_only_affects_weather(backends):
    backends.weather_up = False
    with client_for(backends, ALL) as client:
        body = load_mirror(client)
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
        body = load_mirror(client)

    items = widget(body, "announcements")["data"]["announcements"]
    assert [a["title"] for a in items] == ["Room change", "Exam moved"]  # newest first
    assert items[0]["course"] == "Software Development, CMPT 435L"  # same post in two courses, shown once
    assert items[0]["text"] == "Class is in HC 2023 today."
    assert items[1]["course"] == "CMPT 435L"
    assert len(items[1]["text"]) <= 281 and items[1]["text"].endswith("…")
    assert not any("/courses/13/" in str(r.url) for r in backends.requests)
