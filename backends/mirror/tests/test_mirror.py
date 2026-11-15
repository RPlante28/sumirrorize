"""Runs the mirror backend against a fake database and fake d3l, weather and faces services."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.blink import MAX_CLOSED, STEP_TIMEOUT, BlinkCheck
from app.config import Settings
from app.main import IDENTIFY_BURST, create_app
from app.passes import Passes, Signer
from app.sources import Assignment, Event, course_name
from app.store import Person, WidgetPlacement
from app.widgets import summarize

ZONE = ZoneInfo("America/New_York")
SETTINGS = Settings(
    database_url="unused", d3l_url="http://d3l", d3l_service_key="service-key",
    weather_url="http://weather", faces_url="http://faces", faces_api_key="faces-key", timezone=ZONE,
)
NOW = datetime.now(timezone.utc)
TOKEN_KEY = Fernet.generate_key()
WITH_GOOGLE = replace(SETTINGS, google_client_id="client-id", google_client_secret="client-secret",
                      google_token_key=TOKEN_KEY.decode())


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
    def __init__(self, widgets: list[WidgetPlacement], units: str = "imperial"):
        self.widgets = widgets
        self.units = units

    async def person(self, person_id):
        return {3: Person(3, "Alex Smith"), 4: Person(4, "Riley Jones")}.get(person_id)

    async def enabled_widgets(self, person_id):
        return self.widgets

    async def google_token(self, person_id):
        # person 3 has connected their Google Calendar
        return Fernet(TOKEN_KEY).encrypt(b"3:alex-refresh-token") if person_id == 3 else None

    async def weather_units(self, person_id):
        return self.units


WEATHER = {
    "units": {"temperature": "F", "speed": "mph"},
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
        self.odd_calendar = False
        self.google_up = True
        self.google_requests: list[httpx.Request] = []

    def faces(self, request: httpx.Request) -> httpx.Response:
        """
        The 'frame' is a script: b"face:3" (person 3), b"stranger", b"nobody", b"broken".
        b"face:3!shut" is person 3 with their eyes closed, and b"face:3!half" half open.
        """
        self.face_requests.append(request)
        assert request.headers["authorization"] == "Bearer faces-key"
        if not self.faces_up:
            return httpx.Response(503, json={"error": "down"})
        frame = request.content.decode()
        if frame == "broken":
            return httpx.Response(400, json={"error": "Not a readable image", "code": "bad_image"})
        if frame.startswith("face:"):
            person, _, eyes = frame[5:].partition("!")
            return httpx.Response(200, json={"faces": 1, "match": {"personId": int(person), "similarity": 0.9},
                                             "eyesOpen": {"": 0.98, "shut": 0.02, "half": 0.5}[eyes]})
        nobody = frame == "nobody"
        return httpx.Response(200, json={"faces": 0 if nobody else 1, "match": None, "eyesOpen": None if nobody else 0.98})

    def google(self, request: httpx.Request) -> httpx.Response:
        self.google_requests.append(request)
        if not self.google_up:
            return httpx.Response(503)
        if request.url.host == "oauth2.googleapis.com":
            sent = dict(pair.split("=") for pair in request.content.decode().split("&"))
            assert sent == {"grant_type": "refresh_token", "refresh_token": "alex-refresh-token",
                            "client_id": "client-id", "client_secret": "client-secret"}
            return httpx.Response(200, json={"access_token": "access-1", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer access-1"
        assert request.url.path == "/calendar/v3/calendars/primary/events" and request.url.params["singleEvents"] == "true"
        day = (NOW + timedelta(days=1)).astimezone(ZONE).date()
        return httpx.Response(200, json={"items": [
            {"summary": "Dentist", "location": "Main St", "status": "confirmed",
             "start": {"dateTime": iso(NOW + timedelta(hours=1))}, "end": {"dateTime": iso(NOW + timedelta(hours=2))}},
            {"summary": "Mum's birthday", "start": {"date": day.isoformat()}, "end": {"date": (day + timedelta(days=1)).isoformat()}},
            {"summary": "Cancelled thing", "status": "cancelled",
             "start": {"dateTime": iso(NOW + timedelta(hours=3))}, "end": {"dateTime": iso(NOW + timedelta(hours=4))}},
            {"summary": "Party I said no to", "attendees": [{"self": True, "responseStatus": "declined"}],
             "start": {"dateTime": iso(NOW + timedelta(hours=5))}, "end": {"dateTime": iso(NOW + timedelta(hours=6))}},
            {"summary": "Already over",
             "start": {"dateTime": iso(NOW - timedelta(hours=2))}, "end": {"dateTime": iso(NOW - timedelta(hours=1))}},
            {"start": {"dateTime": iso(NOW + timedelta(days=3))}, "end": {"dateTime": iso(NOW + timedelta(days=3, hours=1))}},
        ]})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "faces":
            return self.faces(request)
        if request.url.host.endswith("googleapis.com"):
            return self.google(request)
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "weather":
            if not self.weather_up:
                return httpx.Response(503, json={"error": "down", "code": "weather_unavailable"})
            return httpx.Response(200, json={**WEATHER, "units": {"temperature": "C" if request.url.params["units"] == "metric" else "F", "speed": "x"}})

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
            if self.odd_calendar:
                return httpx.Response(200, json=[{"Name": "An event in a shape we've never seen"}])
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


def client_for(backends: FakeBackends, widgets: list[WidgetPlacement], settings: Settings = SETTINGS,
               units: str = "imperial") -> TestClient:
    app = create_app(settings, store=FakeStore(widgets, units), transport=httpx.MockTransport(backends))
    return TestClient(app)


def identify(client: TestClient, frame: str, content_type: str = "image/jpeg", blink: Optional[str] = None,
             held_pass: Optional[str] = None):
    headers = {"Content-Type": content_type}
    if blink:
        headers["X-Blink"] = blink
    if held_pass:
        headers["Authorization"] = f"Bearer {held_pass}"
    return client.post("/api/identify", content=frame.encode(), headers=headers)


def watch(client: TestClient, *frames: str) -> dict:
    """Sends frames one after another like the mirror page, passing the blink progress along."""
    body: dict = {}
    for frame in frames:
        body = identify(client, frame, blink=body.get("blink")).json()
    return body


def blink_in(client: TestClient, person: int = 3) -> str:
    """Person looks at the mirror and blinks. Returns their pass."""
    return watch(client, f"face:{person}", f"face:{person}!shut", f"face:{person}")["pass"]


def load_mirror(client: TestClient) -> dict:
    """What the mirror page does: recognize a face, see a blink, then load the mirror with the pass."""
    return client.get("/api/mirror", headers={"Authorization": f"Bearer {blink_in(client)}"}).json()


ALL = [placement(k) for k in ("clock", "greeting", "weather", "calendar", "assignments", "announcements", "summary")]


def widget(body: dict, key: str) -> dict:
    return next(w for w in body["widgets"] if w["key"] == key)


def test_recognized_face_gets_a_pass_after_blinking(backends):
    with client_for(backends, ALL) as client:
        seen = identify(client, "face:3").json()
        assert seen["faces"] == 1 and seen["person"] == {"id": 3, "name": "Alex Smith"}
        assert seen["pass"] is None and seen["blink"]          # recognized, but not let in yet
        shut = identify(client, "face:3!shut", blink=seen["blink"]).json()
        assert shut["pass"] is None and shut["blink"]
        opened = identify(client, "face:3", blink=shut["blink"]).json()
        assert opened["pass"] and opened["expiresAt"] and opened["blink"] is None
    assert backends.face_requests[0].headers["content-type"] == "image/jpeg"


def test_a_photo_never_gets_a_pass(backends):
    with client_for(backends, ALL) as client:
        # Eyes that stay open, stay half open, or stay shut aren't a blink.
        assert watch(client, *["face:3"] * 6)["pass"] is None
        assert watch(client, "face:3", "face:3!half", "face:3")["pass"] is None
        assert watch(client, *["face:3!shut"] * 4, "face:3")["pass"] is None
        # Without the progress from the frame before, every frame is a first frame.
        for frame in ("face:3", "face:3!shut", "face:3"):
            assert identify(client, frame).json()["pass"] is None


def test_blink_must_be_the_same_person_throughout(backends):
    with client_for(backends, ALL) as client:
        # A photo of Alex, then someone else's closed eyes, then the photo again.
        assert watch(client, "face:3", "face:4!shut", "face:3")["pass"] is None
        assert watch(client, "face:3", "stranger", "face:3")["pass"] is None
        # Riley's blink doesn't open Alex's mirror.
        progress = watch(client, "face:4", "face:4!shut")["blink"]
        assert identify(client, "face:3", blink=progress).json()["pass"] is None


def test_blink_steps_and_timing():
    check = BlinkCheck(Signer(b"s" * 32), open_at=0.7, closed_at=0.35)
    _, seen_open = check.step(None, 3, 0.98, now=100)
    _, seen_shut = check.step(seen_open, 3, 0.02, now=100.2)

    assert check.step(seen_shut, 3, 0.98, now=100.4) == (True, None)
    # Half-open frames in the middle of a blink don't spoil it.
    _, closing = check.step(seen_open, 3, 0.5, now=100.1)
    _, shut = check.step(closing, 3, 0.1, now=100.2)
    _, opening = check.step(shut, 3, 0.5, now=100.3)
    assert check.step(opening, 3, 0.9, now=100.4)[0] is True

    # Too slow between frames, or eyes shut for too long: start over.
    assert check.step(seen_open, 3, 0.02, now=100 + STEP_TIMEOUT + 1) == (False, None)
    _, still_shut = check.step(seen_shut, 3, 0.02, now=101.5)
    assert check.step(still_shut, 3, 0.98, now=100.2 + MAX_CLOSED + 0.5)[0] is False
    # Forged, someone else's, or signed by a different server.
    assert check.step(seen_shut[:-2] + "AA", 3, 0.98, now=100.4)[0] is False
    assert check.step(seen_shut, 4, 0.98, now=100.4)[0] is False
    assert BlinkCheck(Signer(b"x" * 32), 0.7, 0.35).step(seen_shut, 3, 0.98, now=100.4)[0] is False
    # Eyes that can't be read change nothing.
    assert check.step(seen_shut, 3, None, now=100.3)[0] is False


def test_pass_renews_while_they_stay(backends):
    with client_for(backends, ALL) as client:
        first = blink_in(client)
        again = identify(client, "face:3", held_pass=first).json()
        assert again["pass"] and again["blink"] is None        # no second blink needed
        # Someone else's pass doesn't let this person in.
        other = identify(client, "face:4", held_pass=first).json()
        assert other["person"]["id"] == 4 and other["pass"] is None


def test_no_pass_for_strangers_or_empty_rooms(backends):
    nothing = {"person": None, "pass": None, "expiresAt": None, "blink": None}
    with client_for(backends, ALL) as client:
        assert identify(client, "stranger").json() == {"faces": 1, **nothing}
        assert identify(client, "nobody").json() == {"faces": 0, **nothing}
        # Recognized, but that person has since been deleted.
        assert watch(client, "face:99", "face:99!shut", "face:99") == {"faces": 1, **nothing}


def test_mirror_needs_a_valid_pass(backends):
    with client_for(backends, ALL) as client:
        assert client.get("/api/mirror").json()["code"] == "pass_expired"
        token = blink_in(client)
        forged = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
        assert client.get("/api/mirror", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
        # The old ways in are gone.
        assert client.get("/api/people").status_code == 404
        assert client.get("/api/people/3/mirror").status_code == 404


def test_passes_expire_and_cant_be_moved():
    signer = Signer(b"s" * 32)
    passes = Passes(signer, lifetime_seconds=60)
    token, _ = passes.issue(3)
    assert passes.check(token) == 3
    assert Passes(signer, lifetime_seconds=-1).check(Passes(signer, -1).issue(3)[0]) is None
    assert Passes(Signer(b"other" * 8), 60).check(token) is None  # signed by a different server
    body, signature = token.split(".")
    other_body = Passes(Signer(b"x" * 32), 60).issue(4)[0].split(".")[0]
    assert passes.check(f"{other_body}.{signature}") is None      # someone else's ID with this signature
    assert passes.check("garbage") is None and passes.check(None) is None
    # Blink progress is signed by the same server, but it isn't a pass.
    _, progress = BlinkCheck(signer, 0.7, 0.35).step(None, 3, 0.98, now=100)
    assert passes.check(progress) is None


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
        codes = [identify(client, "nobody").status_code for _ in range(IDENTIFY_BURST + 10)]
    assert codes[:IDENTIFY_BURST] == [200] * IDENTIFY_BURST and 429 in codes[IDENTIFY_BURST:]


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
    assert "Overcast, high of 44\u00b0F, 40% chance of rain." in text


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


def test_units_follow_person_setting(backends):
    with client_for(backends, [placement("weather")], units="metric") as client:
        body = load_mirror(client)
    assert backends.requests[0].url.params["units"] == "metric"
    assert widget(body, "weather")["data"]["units"]["temperature"] == "C"


def test_units_still_apply_when_weather_widget_is_hidden(backends):
    with client_for(backends, [placement("summary")], units="metric") as client:
        body = load_mirror(client)
    weather = next(request for request in backends.requests if request.url.host == "weather")
    assert weather.url.params["units"] == "metric"
    assert "°C" in widget(body, "summary")["data"]["text"]


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


def test_odd_data_only_affects_its_own_widgets(backends):
    backends.odd_calendar = True
    with client_for(backends, ALL) as client:
        body = load_mirror(client)
    assert widget(body, "calendar")["data"] is None and widget(body, "calendar")["error"]["code"] == "unavailable"
    assert len(widget(body, "assignments")["data"]["assignments"]) == 3
    assert widget(body, "weather")["error"] is None
    assert "calendar" not in widget(body, "summary")["data"]["text"]   # the summary skips what it couldn't get


def test_google_events_join_the_calendar(backends):
    with client_for(backends, ALL, WITH_GOOGLE) as client:
        token = blink_in(client)
        body = client.get("/api/mirror", headers={"Authorization": f"Bearer {token}"}).json()
        client.get("/api/mirror", headers={"Authorization": f"Bearer {token}"})

    events = widget(body, "calendar")["data"]["events"]
    # one list, soonest first. cancelled, declined and finished events are left out
    assert [e["title"] for e in events] == ["Dentist", "Mum's birthday", "Quiz 3", "(no title)"]
    assert events[0]["location"] == "Main St" and events[0]["course"] is None
    assert events[1]["allDay"] is True and events[2]["course"] == "Algorithms"
    # the access token is fetched once and reused
    assert [r.url.host for r in backends.google_requests] == ["oauth2.googleapis.com", "www.googleapis.com", "www.googleapis.com"]


def test_google_calendar_is_optional(backends):
    # this server has no Google settings: nobody is asked
    with client_for(backends, ALL) as client:
        assert [e["title"] for e in widget(load_mirror(client), "calendar")["data"]["events"]] == ["Quiz 3"]
    assert backends.google_requests == []


def test_google_down_still_shows_brightspace(backends):
    backends.google_up = False
    with client_for(backends, ALL, WITH_GOOGLE) as client:
        calendar = widget(load_mirror(client), "calendar")
    assert calendar["error"] is None and [e["title"] for e in calendar["data"]["events"]] == ["Quiz 3"]


def test_google_events_show_without_brightspace(backends):
    backends.signed_in = False
    with client_for(backends, ALL, WITH_GOOGLE) as client:
        body = load_mirror(client)
    calendar = widget(body, "calendar")
    assert calendar["error"] is None and [e["title"] for e in calendar["data"]["events"]][:2] == ["Dentist", "Mum's birthday"]
    assert widget(body, "assignments")["error"]["code"] == "signin_required"
    assert "event" in widget(body, "summary")["data"]["text"]


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
    assert len(items[1]["text"]) <= 283 and items[1]["text"].endswith("...")
    assert not any("/courses/13/" in str(r.url) for r in backends.requests)
