# settings come from env vars (see .env.example)

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    # what the mirror backend and the sign-up app must send
    api_key: str
    models_dir: Path
    # cosine similarity needed to count as the same person. 0.363 is what SFace recommends
    match_threshold: float = 0.363


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set (see .env.example)")
    return value


def load_settings() -> Settings:
    api_key = _required("FACES_API_KEY")
    if len(api_key) < 32:
        raise RuntimeError("FACES_API_KEY must be at least 32 characters")
    threshold = float(os.environ.get("FACES_MATCH_THRESHOLD", "0.363"))
    if not 0 <= threshold <= 1:
        raise RuntimeError("FACES_MATCH_THRESHOLD must be between 0 and 1")
    return Settings(
        database_url=_required("DATABASE_URL"),
        api_key=api_key,
        models_dir=Path(os.environ.get("FACES_MODELS_DIR", "/models")),
        match_threshold=threshold,
    )
