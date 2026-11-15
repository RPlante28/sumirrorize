"""Runs the app with a fake database, a fake Google and fake d3l and faces services."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from cryptography.fernet import Fernet
from flask import redirect

from app.config import Settings
from app.main import GoogleAccount, SignInFailed, create_app
from app.store import DEFAULT_UNITS, Person

ORIGIN = "https://mirror.example"
SETTINGS = Settings(
    public_url=ORIGIN, secret_key="s" * 32, database_url="unused",
    google_client_id="id", google_client_secret="secret", google_token_key=Fernet.generate_key().decode(),
    d3l_url="http://d3l", d3l_service_key="service-key", d3l_public_url=f"{ORIGIN}/api",
    faces_url="http://faces", faces_api_key="faces-key",
)


class FakeStore:
    def __init__(self):
        self.people: dict[int, dict] = {}

    def person(self, person_id):
        p = self.people.get(person_id)
        return Person(person_id, p["name"]) if p else None

    def sign_in(self, google_sub, name):
        for person_id, p in self.people.items():
            if p["sub"] == google_sub:
                return Person(person_id, p["name"]), False
        person_id = len(self.people) + 1
        self.people[person_id] = {"sub": google_sub, "name": name, "units": None, "key_hash": None,
                                  "calendar": None,
                                  "widgets": [
                                      {"key": "clock", "name": "Clock", "enabled": True,
                                       "x": .1, "y": .1, "w": .3, "h": .2, "variant": None},
                                      {"key": "weather", "name": "Weather", "enabled": True,
                                       "x": .6, "y": .1, "w": .3, "h": .2, "variant": None},
                                  ]}
        return Person(person_id, name), True

    def units(self, person_id):
        return self.people[person_id]["units"] or DEFAULT_UNITS

    def set_units(self, person_id, units):
        self.people[person_id]["units"] = units

    def widgets(self, person_id):
        return self.people[person_id]["widgets"]

    def set_widgets(self, person_id, widgets):
        current = self.people[person_id]["widgets"]
        if {widget["key"] for widget in widgets} != {widget["key"] for widget in current}:
            raise ValueError("save every available widget")
        names = {widget["key"]: widget["name"] for widget in current}
        self.people[person_id]["widgets"] = [{**widget, "name": names[widget["key"]]} for widget in widgets]

    def new_api_key(self, person_id):
        key = f"key-{person_id}-{len(str(self.people))}"
        self.people[person_id]["key_hash"] = hashlib.sha256(key.encode()).digest()
        return key

    def calendar_token(self, person_id):
        return self.people[person_id]["calendar"]

    def save_calendar(self, person_id, sealed_token):
        self.people[person_id]["calendar"] = sealed_token

    def forget_calendar(self, person_id):
        self.people[person_id]["calendar"] = None

    def delete_person(self, person_id):
        del self.people[person_id]


class FakeGoogle:
    """Signs in whoever `account` says, or fails when it's None."""

    def __init__(self):
        self.account = GoogleAccount("google-alex", "Alex", calendar=True, refresh_token="alex-calendar-token")
        self.redirect_uri = None
        self.calendar = self.asked_again = False
        self.revoked: list[str] = []

    def start(self, redirect_uri, calendar=False, ask_again=False):
        self.redirect_uri, self.calendar, self.asked_again = redirect_uri, calendar, ask_again
        return redirect("https://accounts.google.com/o/oauth2/auth?fake")

    def revoke(self, refresh_token):
        self.revoked.append(refresh_token)

    def finish(self):
        if self.account is None:
            raise SignInFailed("access_denied")
        return self.account


class FakeServices:
    """d3l and faces. Records each call; set `down` to make a service unreachable."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.signed_in: set[int] = set()
        self.pictures: dict[int, list] = {}
        self.down: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host, method, path = request.url.host, request.method, request.url.path
        if host in self.down:
            raise httpx.ConnectError("down")
        self.calls.append((host, f"{method} {path}", dict(request.headers)))
        if host == "d3l":
            assert request.headers["authorization"] == "Bearer service-key"
            person = int(request.headers["x-person-id"])
            if (method, path) == ("POST", "/login"):
                return httpx.Response(201, json={"path": "/login/one-time-token", "expiresAt": "soon"})
            if (method, path) == ("GET", "/session"):
                return httpx.Response(200, json={"signedIn": person in self.signed_in, "signedInAt": None,
                                                 "signingIn": False})
            if (method, path) == ("DELETE", "/session"):
                self.signed_in.discard(person)
                return httpx.Response(204)
        if host == "faces":
            assert request.headers["authorization"] == "Bearer faces-key"
            person = int(path.split("/")[2])
            if method == "GET":
                return httpx.Response(200, json={"pictures": [{"angle": a, "savedAt": "x"}
                                                              for a in self.pictures.get(person, [])]})
            if method == "PUT":
                pictures = json.loads(request.content)["pictures"]
                problems = [{"angle": p["angle"], "problem": "too_small" if "small" in p["image"] else None}
                            for p in pictures]
                if any(p["problem"] for p in problems):
                    return httpx.Response(422, json={"error": "Some pictures need retaking",
                                                     "code": "poor_pictures", "pictures": problems})
                self.pictures[person] = [p["angle"] for p in pictures]
                return httpx.Response(200, json={"saved": len(pictures), "pictures": problems})
        return httpx.Response(404, json={"error": "no route", "code": "not_found"})


@pytest.fixture
def world():
    store, google, services = FakeStore(), FakeGoogle(), FakeServices()
    app = create_app(SETTINGS, store=store, google=google, transport=httpx.MockTransport(services))
    app.testing = True
    client = app.test_client()
    return client, store, google, services


def sign_in(client):
    return client.get("/login/callback?code=x&state=y")


def send(client, method, path, body=None, origin=ORIGIN):
    headers = {"Origin": origin} if origin else {}
    return client.open(path, method=method, json=body, headers=headers)


def test_signed_out(world):
    client, *_ = world
    page = client.get("/")
    assert page.status_code == 200 and b"Continue with Google" in page.data
    assert client.get("/faces").headers["Location"] == "/"
    assert send(client, "PUT", "/me/units", {"units": "metric"}).json["code"] == "signed_out"


def test_google_sign_in_makes_a_person_once(world):
    client, store, google, _ = world
    assert client.get("/login").status_code == 302
    assert google.redirect_uri == f"{ORIGIN}/login/callback"

    first = sign_in(client)
    assert first.headers["Location"] == "/faces"  # new people start with their face pictures
    assert store.people[1]["name"] == "Alex"

    send(client, "POST", "/logout")
    again = sign_in(client)
    assert again.headers["Location"] == "/"
    assert len(store.people) == 1


def test_failed_google_sign_in(world):
    client, store, google, _ = world
    google.account = None
    response = sign_in(client)
    assert response.status_code == 400 and b"didn&#39;t finish" in response.data
    assert store.people == {}


def test_settings_page_shows_status(world):
    client, _, _, services = world
    sign_in(client)
    page = client.get("/").get_data(as_text=True)
    assert "Hi, Alex" in page and "Not set up yet" in page and 'data-state="disconnected"' in page

    services.pictures[1] = ["front", "left"]
    services.signed_in.add(1)
    page = client.get("/").get_data(as_text=True)
    assert "Set up (2 pictures)" in page and 'data-state="connected"' in page


def test_settings_page_survives_services_down(world):
    client, _, _, services = world
    sign_in(client)
    services.down |= {"d3l", "faces"}
    page = client.get("/")
    assert page.status_code == 200
    assert 'data-state="unknown"' in page.get_data(as_text=True)


def test_changes_need_our_origin(world):
    client, store, *_ = world
    sign_in(client)
    for origin in (None, "https://evil.example"):
        response = send(client, "PUT", "/me/units", {"units": "metric"}, origin=origin)
        assert response.status_code == 403 and response.json["code"] == "bad_origin"
    assert store.people[1]["units"] is None


def test_units(world):
    client, store, *_ = world
    sign_in(client)
    assert send(client, "PUT", "/me/units", {"units": "metric"}).json == {"units": "metric"}
    assert store.people[1]["units"] == "metric"
    assert send(client, "PUT", "/me/units", {"units": "kelvin"}).json["code"] == "bad_request"


def test_layout_page_and_save(world):
    client, store, *_ = world
    sign_in(client)
    assert client.get("/layout").status_code == 200
    widgets = store.widgets(1)
    widgets[0] = {**widgets[0], "x": .2, "variant": "time"}
    widgets[1] = {**widgets[1], "variant": "hourly"}
    assert send(client, "PUT", "/me/widgets", {"widgets": widgets}).json == {"ok": True}
    assert store.widgets(1)[0]["x"] == .2
    assert store.widgets(1)[1]["variant"] == "hourly"


def test_layout_save_is_all_or_nothing(world):
    client, store, *_ = world
    sign_in(client)
    before = list(store.widgets(1))
    response = send(client, "PUT", "/me/widgets", {"widgets": [before[0]]})
    assert response.status_code == 400 and response.json["code"] == "bad_layout"
    assert store.widgets(1) == before


def test_save_faces(world):
    client, _, _, services = world
    sign_in(client)
    pictures = [{"angle": "front", "image": "data:image/jpeg;base64,ok"},
                {"angle": "left", "image": "data:image/jpeg;base64,ok"}]
    assert send(client, "PUT", "/me/faces", {"pictures": pictures}).json["saved"] == 2
    assert services.pictures[1] == ["front", "left"]


def test_poor_faces_say_which_to_retake(world):
    client, _, _, services = world
    sign_in(client)
    pictures = [{"angle": "front", "image": "data:image/jpeg;base64,ok"},
                {"angle": "left", "image": "data:image/jpeg;base64,small"}]
    response = send(client, "PUT", "/me/faces", {"pictures": pictures})
    assert response.status_code == 422
    assert response.json["code"] == "poor_pictures"
    assert [p["problem"] for p in response.json["pictures"]] == [None, "too_small"]
    assert 1 not in services.pictures


def test_bad_face_requests(world):
    client, _, _, services = world
    sign_in(client)
    assert send(client, "PUT", "/me/faces", {"pictures": []}).json["code"] == "bad_request"
    assert send(client, "PUT", "/me/faces", {"nope": 1}).json["code"] == "bad_request"
    services.down.add("faces")
    response = send(client, "PUT", "/me/faces", {"pictures": [{"angle": "front", "image": "x"}]})
    assert response.status_code == 503 and response.json["code"] == "faces_unavailable"


def test_connect_brightspace(world):
    client, _, _, services = world
    sign_in(client)
    started = send(client, "POST", "/me/brightspace").json
    assert started["url"] == f"{ORIGIN}/api/login/one-time-token"
    assert ("d3l", "POST /login") in [(h, c) for h, c, _ in services.calls]
    assert services.calls[-1][2]["x-person-id"] == "1"

    assert client.get("/me/brightspace").json["signedIn"] is False
    services.signed_in.add(1)
    assert client.get("/me/brightspace").json["signedIn"] is True
    assert send(client, "DELETE", "/me/brightspace").status_code == 204
    assert 1 not in services.signed_in


def test_d3l_down(world):
    client, _, _, services = world
    sign_in(client)
    services.down.add("d3l")
    response = send(client, "POST", "/me/brightspace")
    assert response.status_code == 503 and response.json["code"] == "d3l_unavailable"


def test_api_key(world):
    client, store, *_ = world
    sign_in(client)
    key = send(client, "POST", "/me/api-key").json["apiKey"]
    assert store.people[1]["key_hash"] == hashlib.sha256(key.encode()).digest()


def test_delete_account(world):
    client, store, _, services = world
    sign_in(client)
    services.signed_in.add(1)
    assert send(client, "DELETE", "/me").status_code == 204
    assert store.people == {}
    assert 1 not in services.signed_in  # d3l was told first
    assert client.get("/").data.count(b"Continue with Google") == 1  # signed out


def test_delete_account_waits_for_d3l(world):
    client, store, _, services = world
    sign_in(client)
    services.down.add("d3l")
    assert send(client, "DELETE", "/me").status_code == 503
    assert 1 in store.people


def test_calendar_connects_when_google_sends_a_token(world):
    client, store, google, _ = world
    sign_in(client)
    sealed = store.people[1]["calendar"]
    assert sealed and b"alex-calendar-token" not in sealed       # saved, and not readable as is
    assert "Connected. Your events" in client.get("/").get_data(as_text=True)

    # Later sign-ins don't come with a token (Google only sends it when it asks). The saved one stays.
    send(client, "POST", "/logout")
    google.account = GoogleAccount("google-alex", "Alex", calendar=True, refresh_token=None)
    sign_in(client)
    assert store.people[1]["calendar"] == sealed


def test_calendar_not_connected_if_they_say_no(world):
    client, store, google, _ = world
    google.account = GoogleAccount("google-alex", "Alex", calendar=False, refresh_token="unrelated")
    sign_in(client)
    assert store.people[1]["calendar"] is None
    page = client.get("/").get_data(as_text=True)
    assert "Connect Google Calendar" in page and "/login?calendar=1" in page

    # plain sign-in only asks who they are. the Connect button asks for the calendar
    client.get("/login")
    assert (google.calendar, google.asked_again) == (False, False)
    client.get("/login?calendar=1")
    assert (google.calendar, google.asked_again) == (True, True)


def test_calendar_can_be_asked_for_at_every_sign_in():
    google = FakeGoogle()
    app = create_app(replace(SETTINGS, calendar_at_sign_in=True), store=FakeStore(), google=google,
                     transport=httpx.MockTransport(FakeServices()))
    app.test_client().get("/login")
    assert (google.calendar, google.asked_again) == (True, False)


def test_disconnect_calendar(world):
    client, store, google, _ = world
    sign_in(client)
    assert send(client, "DELETE", "/me/calendar").status_code == 204
    assert store.people[1]["calendar"] is None
    assert google.revoked == ["alex-calendar-token"]             # Google is told too


def test_deleting_account_drops_calendar_access(world):
    client, store, google, _ = world
    sign_in(client)
    assert send(client, "DELETE", "/me").status_code == 204
    assert google.revoked == ["alex-calendar-token"] and store.people == {}


def test_privacy_and_terms_are_public(world):
    client, *_ = world
    privacy = client.get("/privacy")
    assert privacy.status_code == 200
    text = privacy.get_data(as_text=True)
    assert "Google API Services" in text and "Limited Use" in text and "Delete my account" in text
    assert client.get("/terms").status_code == 200 and b"Terms of Service" in client.get("/terms").data
    # the sign-in page links to both, which Google checks for
    home = client.get("/").get_data(as_text=True)
    assert 'href="/privacy"' in home and 'href="/terms"' in home


def test_contact_email_is_shown_when_set():
    app = create_app(replace(SETTINGS, contact_email="team@mirror.example"), store=FakeStore(), google=FakeGoogle(),
                     transport=httpx.MockTransport(FakeServices()))
    assert b"mailto:team@mirror.example" in app.test_client().get("/privacy").data


def test_security_headers(world):
    client, *_ = world
    headers = client.get("/").headers
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "script-src" not in headers["Content-Security-Policy"]  # default-src 'self' covers it
    assert headers["Permissions-Policy"].startswith("camera=(self)")
    assert headers["Cache-Control"] == "no-store"
    assert "no-store" not in client.get("/static/style.css").headers.get("Cache-Control", "")
