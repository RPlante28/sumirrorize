"""
The faces service: the only part of Sumirrorize that handles face pictures and fingerprints.
Internal only; the mirror backend and the sign-up app call it with FACES_API_KEY. Run with:
    uvicorn --factory app.main:create_app --port 3400
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import logging
import re
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import Settings, load_settings
from .engine import BadImage, Engine, OpenCvEngine, enrollment_problem, mirror_face
from .store import NewPicture, PostgresStore, Store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PICTURES = 20  # the face-recog enrollment script takes 20
ANGLE = re.compile(r"^[a-z][a-z0-9_]*$")
DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,(.*)$", re.S)


class ApiError(HTTPException):
    def __init__(self, status: int, message: str, code: str, **extra):
        super().__init__(status, message)
        self.code = code
        self.extra = extra


class PictureIn(BaseModel):
    angle: str = Field(description="Which shot this is, e.g. front, left, right")
    image: str = Field(description='A data URL ("data:image/jpeg;base64,...") as a canvas produces')


class Enrollment(BaseModel):
    pictures: list[PictureIn]


def _decode(picture: PictureIn) -> tuple[bytes, str]:
    match = DATA_URL.match(picture.image)
    if not match:
        raise ApiError(400, f"{picture.angle}: image must be a JPEG, PNG or WebP data URL", "bad_image")
    try:
        data = base64.b64decode(match[2], validate=True)
    except binascii.Error:
        raise ApiError(400, f"{picture.angle}: image isn't valid base64", "bad_image") from None
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ApiError(413, f"{picture.angle}: image must be under 5 MB", "too_large")
    return data, match[1]


def create_app(settings: Optional[Settings] = None, store: Optional[Store] = None,
               engine: Optional[Engine] = None) -> FastAPI:
    """`store` and `engine` let tests swap in a fake database and fake face models."""
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = engine or OpenCvEngine(settings.models_dir)
        db = store or await PostgresStore.connect(settings.database_url)
        app.state.store = db
        yield
        if isinstance(db, PostgresStore):
            await db.close()

    app = FastAPI(title="Sumirrorize faces", lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, error: ApiError):
        return JSONResponse(status_code=error.status_code,
                            content={"error": error.detail, "code": error.code, **error.extra})

    @app.exception_handler(RequestValidationError)
    async def bad_request(_request: Request, error: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": str(error.errors()[0]["msg"]), "code": "bad_request"})

    def require_key(request: Request) -> None:
        sent = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not hmac.compare_digest(sent.encode(), settings.api_key.encode()):
            raise ApiError(401, "Missing or wrong API key", "bad_api_key")

    async def analyze(request: Request, image: bytes):
        try:
            return await asyncio.to_thread(request.app.state.engine.analyze, image)
        except BadImage as error:
            raise ApiError(400, str(error), "bad_image") from None

    @app.post("/identify", dependencies=[Depends(require_key)])
    async def identify(request: Request):
        """Who's in this picture? Send the image itself as the body (e.g. image/jpeg)."""
        image = await request.body()
        if not image or len(image) > MAX_IMAGE_BYTES:
            raise ApiError(413, "Send one image under 5 MB as the request body", "too_large")
        analysis = await analyze(request, image)
        face = mirror_face(analysis)
        match = await request.app.state.store.closest(face.fingerprint) if face is not None else None
        recognized = match is not None and match.similarity >= settings.match_threshold
        return {
            "faces": len(analysis.faces),
            "match": {"personId": match.person_id, "similarity": round(match.similarity, 3)} if recognized else None,
        }

    @app.put("/people/{person_id}/faces", dependencies=[Depends(require_key)])
    async def enroll(person_id: int, body: Enrollment, request: Request):
        """
        Replaces a person's face pictures. Every picture must show exactly one clear face; if any
        doesn't, nothing is saved and `pictures` says which to retake and why.
        """
        if not body.pictures or len(body.pictures) > MAX_PICTURES:
            raise ApiError(400, f"Send between 1 and {MAX_PICTURES} pictures", "bad_request")
        if not await request.app.state.store.person_exists(person_id):
            raise ApiError(404, f"No person with ID {person_id}", "no_such_person")

        results, new = [], []
        for picture in body.pictures:
            if not ANGLE.match(picture.angle):
                raise ApiError(400, f"Bad angle {picture.angle!r}: use lowercase letters, e.g. front", "bad_request")
            data, mime = _decode(picture)
            analysis = await analyze(request, data)
            problem = enrollment_problem(analysis)
            results.append({"angle": picture.angle, "problem": problem})
            if problem is None:
                new.append(NewPicture(picture.angle, data, mime, analysis.faces[0].fingerprint))

        if len(new) < len(body.pictures):
            raise ApiError(422, "Some pictures need retaking", "poor_pictures", pictures=results)
        await request.app.state.store.replace_pictures(person_id, new)
        logger.info("Saved %d face pictures for person %d", len(new), person_id)
        return {"saved": len(new), "pictures": results}

    @app.delete("/people/{person_id}/faces", dependencies=[Depends(require_key)])
    async def forget(person_id: int, request: Request):
        """Deletes a person's face pictures; they won't be recognized until they sign up again."""
        return {"deleted": await request.app.state.store.delete_pictures(person_id)}

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app
