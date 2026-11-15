"""
The mirror's backend. Run with:
    uvicorn --factory app.main:create_app --port 3300

Your face is the key: the mirror page sends camera frames to /api/identify. Once the faces
service recognizes someone and the server has seen them blink (so a photo of them won't do), the
page gets a short-lived pass for loading their widgets from /api/mirror. There's no other way to
get a person's data from here.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import widgets
from .blink import BlinkCheck
from .config import Settings, load_settings
from .passes import Passes, Signer
from .ratelimit import RateLimiter, client_address
from .sources import D3l, Faces, SourceError, Weather
from .store import PostgresStore, Store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

PASS_LIFETIME = 120            # seconds; the page renews it on every recognition
# How often one address may ask "who is this?". A mirror asks about twice a second, and several
# times a second for the moment it's waiting for a blink. A shared wifi network is one address.
IDENTIFY_PER_SECOND = 12
IDENTIFY_BURST = 40
MAX_FRAME_BYTES = 2 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


class ApiError(HTTPException):
    def __init__(self, status: int, message: str, code: str):
        super().__init__(status, message)
        self.code = code


def create_app(
    settings: Optional[Settings] = None,
    store: Optional[Store] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> FastAPI:
    """`store` and `transport` let tests swap in a fake database and fake backends."""
    settings = settings or load_settings()
    signer = Signer()
    passes = Passes(signer, PASS_LIFETIME)
    blink = BlinkCheck(signer, settings.eyes_open_at, settings.eyes_closed_at)
    limiter = RateLimiter(per_second=IDENTIFY_PER_SECOND, burst=IDENTIFY_BURST)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = store or await PostgresStore.connect(settings.database_url)
        async with httpx.AsyncClient(transport=transport, timeout=30) as client:
            app.state.store = db
            app.state.d3l = D3l(client, settings.d3l_url, settings.d3l_service_key)
            app.state.weather = Weather(client, settings.weather_url)
            app.state.faces = Faces(client, settings.faces_url, settings.faces_api_key)
            yield
        if isinstance(db, PostgresStore):
            await db.close()

    app = FastAPI(title="Sumirrorize mirror", lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, error: ApiError):
        return JSONResponse(status_code=error.status_code, content={"error": error.detail, "code": error.code})

    def pass_holder(request: Request) -> Optional[int]:
        return passes.check(request.headers.get("authorization", "").removeprefix("Bearer "))

    def person_with_pass(request: Request) -> int:
        person_id = pass_holder(request)
        if person_id is None:
            raise ApiError(401, "Missing or expired pass; recognize a face first", "pass_expired")
        return person_id

    @app.post("/api/identify")
    async def identify(request: Request):
        """
        Who's at the mirror? Send one camera frame as the body (image/jpeg). The answer says who
        was recognized, and once they've blinked it includes a pass for /api/mirror.

        Until then it includes `blink`, their progress towards a blink: send it back with the
        next frame in an X-Blink header. Sending the current pass (Authorization: Bearer) while
        the same person is still there swaps it for a fresh one without another blink.
        """
        if not limiter.allow(client_address(request)):
            raise ApiError(429, "Too many requests, slow down", "rate_limited")
        content_type = request.headers.get("content-type", "").split(";")[0].strip()
        if content_type not in IMAGE_TYPES:
            raise ApiError(415, "Send a JPEG, PNG or WebP image", "bad_image")
        frame = await request.body()
        if not frame or len(frame) > MAX_FRAME_BYTES:
            raise ApiError(413, "Send one image under 2 MB", "too_large")

        state = request.app.state
        try:
            found = await state.faces.identify(frame, content_type)
        except SourceError as error:
            raise ApiError(400 if error.code == "bad_image" else 503, error.message, error.code) from None

        person = await state.store.person(found.person_id) if found.person_id is not None else None
        answer = {"faces": found.faces, "person": None, "pass": None, "expiresAt": None, "blink": None}
        if person is None:
            return answer
        answer["person"] = {"id": person.id, "name": person.name}

        progress = None
        blinked = pass_holder(request) == person.id   # already let in, and still here
        if not blinked:
            blinked, progress = blink.step(request.headers.get("x-blink"), person.id, found.eyes_open, time.time())
        if blinked:
            token, expires = passes.issue(person.id)
            return {**answer, "pass": token, "expiresAt": expires.isoformat()}
        return {**answer, "blink": progress}

    @app.get("/api/mirror")
    async def mirror(request: Request, person_id: int = Depends(person_with_pass)):
        """Everything the recognized person's mirror shows: their enabled widgets, placed, with data."""
        state = request.app.state
        person = await state.store.person(person_id)
        if not person:
            raise ApiError(401, "This person no longer exists", "pass_expired")
        placements = await state.store.enabled_widgets(person_id)
        return {
            "person": {"id": person.id, "name": person.name},
            "timezone": settings.timezone.key,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "widgets": await widgets.build(person, placements, state.d3l, state.weather, settings.timezone),
        }

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    return app
