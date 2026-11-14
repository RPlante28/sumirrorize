"""
The mirror's backend. Run with:
    uvicorn --factory app.main:create_app --port 3300

For now the mirror picks who's standing in front of it from a list. Face recognition will
replace that step; everything after it (gathering the person's widgets) stays the same.
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import widgets
from .config import Settings, load_settings
from .sources import D3l, Weather
from .store import PostgresStore, Store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = store or await PostgresStore.connect(settings.database_url)
        async with httpx.AsyncClient(transport=transport, timeout=30) as client:
            app.state.store = db
            app.state.d3l = D3l(client, settings.d3l_url, settings.d3l_service_key)
            app.state.weather = Weather(client, settings.weather_url)
            yield
        if isinstance(db, PostgresStore):
            await db.close()

    app = FastAPI(title="Sumirrorize mirror", lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, error: ApiError):
        return JSONResponse(status_code=error.status_code, content={"error": error.detail, "code": error.code})

    def require_mirror_key(request: Request) -> None:
        sent = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(sent.encode(), settings.mirror_key.encode()):
            raise ApiError(401, "Missing or wrong mirror key", "bad_mirror_key")

    @app.get("/api/people", dependencies=[Depends(require_mirror_key)])
    async def people(request: Request):
        """Everyone the mirror knows, for picking who's at the mirror."""
        return [{"id": p.id, "name": p.name} for p in await request.app.state.store.people()]

    @app.get("/api/people/{person_id}/mirror", dependencies=[Depends(require_mirror_key)])
    async def mirror(person_id: int, request: Request):
        """Everything one person's mirror shows: their enabled widgets, placed, with data."""
        state = request.app.state
        person = await state.store.person(person_id)
        if not person:
            raise ApiError(404, f"No person with ID {person_id}", "no_such_person")
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
