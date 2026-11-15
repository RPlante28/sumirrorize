# settings come from env vars (see .env.example)

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set (see .env.example)")
    return value


@dataclass(frozen=True)
class Settings:
    # where people open the app. Google sends them back to <public_url>/login/callback
    public_url: str
    # signs the login cookie
    secret_key: str
    database_url: str
    google_client_id: str
    google_client_secret: str
    # encrypts saved Google Calendar tokens. the mirror backend needs the same one
    google_token_key: str
    # d3l inside the server network, and its SERVICE_API_KEY
    d3l_url: str
    d3l_service_key: str
    # where browsers reach d3l, for the Brightspace sign-in tab
    d3l_public_url: str
    faces_url: str
    faces_api_key: str

    @property
    def origin(self) -> str:
        """Scheme and host of public_url, which browsers send as Origin."""
        parts = urlsplit(self.public_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")


def load_settings() -> Settings:
    secret_key = _required("APP_SECRET_KEY")
    if len(secret_key) < 32:
        raise RuntimeError("APP_SECRET_KEY must be at least 32 characters (openssl rand -hex 32)")
    return Settings(
        public_url=_required("APP_PUBLIC_URL").rstrip("/"),
        secret_key=secret_key,
        database_url=_required("DATABASE_URL"),
        google_client_id=_required("GOOGLE_CLIENT_ID"),
        google_client_secret=_required("GOOGLE_CLIENT_SECRET"),
        google_token_key=_required("GOOGLE_TOKEN_KEY"),
        d3l_url=_required("D3L_URL").rstrip("/"),
        d3l_service_key=_required("D3L_SERVICE_KEY"),
        d3l_public_url=_required("D3L_PUBLIC_URL").rstrip("/"),
        faces_url=_required("FACES_URL").rstrip("/"),
        faces_api_key=_required("FACES_API_KEY"),
    )
