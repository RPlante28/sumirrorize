"""Runs the faces service with fake face models and an in-memory database."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.engine import Analysis, BadImage, Face
from app.main import create_app
from app.store import Match, SavedPicture

KEY = "faces-key-0123456789abcdef0123456789ab"
SETTINGS = Settings(database_url="unused", api_key=KEY, models_dir=None)  # type: ignore[arg-type]


def direction(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


ALEX, RILEY = direction(1), direction(2)


class FakeEngine:
    """
    Reads the 'picture' as a script: b"face:alex", b"faces:2", b"dark", b"small", b"none", b"broken".
    b"face:alex~0.3" adds noise to the fingerprint, and b"face:alex!shut" closes their eyes.
    """

    def analyze(self, image: bytes) -> Analysis:
        text = image.decode(errors="replace")
        if text == "broken":
            raise BadImage("Not a readable image")
        if text == "none":
            return Analysis([])
        if text == "faces:2":
            return Analysis([Face(150, 120, ALEX, 1.0), Face(140, 120, RILEY, 1.0)])
        if text == "dark":
            return Analysis([Face(150, 10, ALEX, 1.0)])
        if text == "small":
            return Analysis([Face(50, 120, ALEX, 1.0)])
        if text == "far":                       # big enough to sign up with? no. At the mirror? no.
            return Analysis([Face(40, 120, ALEX, 1.0)])
        text, _, eyes = text.removeprefix("face:").partition("!")
        name, _, noise = text.partition("~")
        base = {"alex": ALEX, "riley": RILEY}[name]
        fingerprint = base + (direction(99) * float(noise) if noise else 0)
        return Analysis([Face(150, 120, fingerprint.astype(np.float32), 0.02 if eyes == "shut" else 0.98)])


class FakeStore:
    def __init__(self):
        self.pictures: dict[int, list] = {}

    async def person_exists(self, person_id):
        return person_id in (3, 4)

    async def saved_pictures(self, person_id):
        saved_at = datetime(2026, 11, 14, tzinfo=timezone.utc)
        return [SavedPicture(p.angle, saved_at) for p in self.pictures.get(person_id, [])]

    async def replace_pictures(self, person_id, pictures):
        self.pictures[person_id] = list(pictures)

    async def delete_pictures(self, person_id):
        return len(self.pictures.pop(person_id, []))

    async def closest(self, fingerprint) -> Optional[Match]:
        best = None
        for person_id, pictures in self.pictures.items():
            for p in pictures:
                sim = float(np.dot(fingerprint, p.fingerprint) / (np.linalg.norm(fingerprint) * np.linalg.norm(p.fingerprint)))
                if best is None or sim > best.similarity:
                    best = Match(person_id, sim)
        return best


def data_url(script: str, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(script.encode()).decode()}"


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def client(store) -> TestClient:
    app = create_app(SETTINGS, store=store, engine=FakeEngine())
    with TestClient(app, headers={"Authorization": f"Bearer {KEY}"}) as c:
        yield c


def enroll(client, person_id, **pictures):
    return client.put(f"/people/{person_id}/faces",
                      json={"pictures": [{"angle": a, "image": data_url(s)} for a, s in pictures.items()]})


def identify(client, script: str):
    return client.post("/identify", content=script.encode(), headers={"Content-Type": "image/jpeg"})


def test_needs_key(store):
    with TestClient(create_app(SETTINGS, store=store, engine=FakeEngine())) as c:
        assert c.post("/identify", content=b"face:alex").json()["code"] == "bad_api_key"
        assert c.put("/people/3/faces", json={"pictures": []}).status_code == 401


def test_enroll_then_recognize(client, store):
    response = enroll(client, 3, front="face:alex", left="face:alex~0.3", right="face:alex~0.4")
    assert response.status_code == 200
    assert response.json() == {"saved": 3, "pictures": [
        {"angle": "front", "problem": None}, {"angle": "left", "problem": None}, {"angle": "right", "problem": None}]}
    assert [p.angle for p in store.pictures[3]] == ["front", "left", "right"]
    assert store.pictures[3][0].image == b"face:alex" and store.pictures[3][0].mime_type == "image/jpeg"

    body = identify(client, "face:alex~0.5").json()
    assert body["faces"] == 1 and body["match"]["personId"] == 3 and body["match"]["similarity"] > 0.8


def test_says_how_open_the_eyes_are(client):
    enroll(client, 3, front="face:alex")
    assert identify(client, "face:alex").json()["eyesOpen"] == 0.98
    assert identify(client, "face:alex!shut").json()["eyesOpen"] == 0.02
    assert identify(client, "face:riley").json()["eyesOpen"] == 0.98   # measured even for strangers
    assert identify(client, "none").json()["eyesOpen"] is None


def test_stranger_not_recognized(client):
    enroll(client, 3, front="face:alex")
    assert identify(client, "face:riley").json() == {"faces": 1, "match": None, "eyesOpen": 0.98}


def test_tells_two_people_apart(client):
    enroll(client, 3, front="face:alex")
    enroll(client, 4, front="face:riley")
    assert identify(client, "face:riley~0.2").json()["match"]["personId"] == 4
    assert identify(client, "face:alex~0.2").json()["match"]["personId"] == 3


def test_nobody_there(client):
    enroll(client, 3, front="face:alex")
    assert identify(client, "none").json() == {"faces": 0, "match": None, "eyesOpen": None}


def test_far_away_face_ignored(client):
    enroll(client, 3, front="face:alex")
    assert identify(client, "far").json() == {"faces": 1, "match": None, "eyesOpen": None}


def test_largest_face_wins(client):
    enroll(client, 4, front="face:riley")
    # Two faces: the bigger (closer) one is Alex, who isn't signed up, so no match even though Riley is there.
    assert identify(client, "faces:2").json()["match"] is None


def test_poor_pictures_rejected_and_nothing_saved(client, store):
    enroll(client, 3, front="face:alex")
    response = enroll(client, 3, front="face:alex", left="none", right="dark", up="small", down="faces:2")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "poor_pictures"
    assert [p["problem"] for p in body["pictures"]] == [None, "no_face", "bad_lighting", "too_small", "several_faces"]
    assert len(store.pictures[3]) == 1  # the old set is untouched


def test_pictures_must_all_be_the_same_person(client, store):
    response = enroll(client, 3, front="face:alex", left="face:alex~0.3", right="face:riley", up="face:alex~0.4")
    assert response.status_code == 422
    assert [p["problem"] for p in response.json()["pictures"]] == [None, None, "different_person", None]
    assert 3 not in store.pictures

    # Checked together with the other problems, so everything to retake is listed at once.
    response = enroll(client, 3, front="face:alex", left="dark", right="face:riley", up="face:alex~0.3")
    assert [p["problem"] for p in response.json()["pictures"]] == [None, "bad_lighting", "different_person", None]


def test_new_upload_replaces_old_set(client, store):
    enroll(client, 3, front="face:alex", left="face:alex")
    enroll(client, 3, front="face:alex~0.1")
    assert len(store.pictures[3]) == 1


def test_bad_requests(client):
    assert enroll(client, 99, front="face:alex").json()["code"] == "no_such_person"
    assert client.put("/people/3/faces", json={"pictures": []}).json()["code"] == "bad_request"
    assert enroll(client, 3, Front="face:alex").json()["code"] == "bad_request"  # angle must be lowercase
    bad = client.put("/people/3/faces", json={"pictures": [{"angle": "front", "image": "data:text/plain;base64,aGk="}]})
    assert bad.json()["code"] == "bad_image"
    assert enroll(client, 3, front="broken").json()["code"] == "bad_image"
    assert identify(client, "broken").json()["code"] == "bad_image"
    assert client.post("/identify", content=b"").json()["code"] == "too_large"


def test_list_saved_pictures(client):
    assert client.get("/people/3/faces").json() == {"pictures": []}
    enroll(client, 3, front="face:alex", left="face:alex~0.2")
    body = client.get("/people/3/faces").json()
    assert [p["angle"] for p in body["pictures"]] == ["front", "left"]
    assert "image" not in body["pictures"][0]
    assert client.get("/people/99/faces").json()["code"] == "no_such_person"


def test_forget(client, store):
    enroll(client, 3, front="face:alex")
    assert client.delete("/people/3/faces").json() == {"deleted": 1}
    assert identify(client, "face:alex").json()["match"] is None
