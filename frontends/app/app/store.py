# people and their settings. face pictures go through the faces service instead

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional, Protocol

from psycopg_pool import ConnectionPool

UNITS = ("imperial", "metric")
DEFAULT_UNITS = "imperial"  # used when the weather widget has no setting


@dataclass(frozen=True)
class Person:
    id: int
    name: str


def make_api_key() -> tuple[str, bytes]:
    """A new API key and its SHA-256 hash. Only the hash is stored."""
    key = secrets.token_urlsafe(32)
    return key, hashlib.sha256(key.encode()).digest()


class Store(Protocol):
    def person(self, person_id: int) -> Optional[Person]: ...
    def sign_in(self, google_sub: str, name: str) -> tuple[Person, bool]: ...
    def units(self, person_id: int) -> str: ...
    def set_units(self, person_id: int, units: str) -> None: ...
    def new_api_key(self, person_id: int) -> str: ...
    def calendar_token(self, person_id: int) -> Optional[bytes]: ...
    def save_calendar(self, person_id: int, sealed_token: bytes) -> None: ...
    def forget_calendar(self, person_id: int) -> None: ...
    def delete_person(self, person_id: int) -> None: ...


class PostgresStore:
    def __init__(self, url: str):
        self._pool = ConnectionPool(url, min_size=1, max_size=4, open=True)

    def close(self) -> None:
        self._pool.close()

    def person(self, person_id: int) -> Optional[Person]:
        with self._pool.connection() as db:
            row = db.execute("SELECT person_id, display_name FROM person WHERE person_id = %s",
                             (person_id,)).fetchone()
        return Person(*row) if row else None

    def sign_in(self, google_sub: str, name: str) -> tuple[Person, bool]:
        """The person with this Google account, made on their first sign-in. True if just made."""
        find = "SELECT person_id, display_name FROM person WHERE google_sub = %s"
        with self._pool.connection() as db:
            row = db.execute(find, (google_sub,)).fetchone()
            if row:
                return Person(*row), False
            # everyone needs a key hash. nobody sees this key, they can ask for one later
            _, key_hash = make_api_key()
            row = db.execute(
                """INSERT INTO person (display_name, api_key_hash, google_sub) VALUES (%s, %s, %s)
                   ON CONFLICT (google_sub) DO NOTHING RETURNING person_id, display_name""",
                (name, key_hash, google_sub),
            ).fetchone()
            if row:
                return Person(*row), True
            # signed in twice at once and the other request made them first
            return Person(*db.execute(find, (google_sub,)).fetchone()), False

    def units(self, person_id: int) -> str:
        with self._pool.connection() as db:
            row = db.execute(
                "SELECT settings->>'units' FROM person_widget WHERE person_id = %s AND widget_key = 'weather'",
                (person_id,),
            ).fetchone()
        return row[0] if row and row[0] in UNITS else DEFAULT_UNITS

    def set_units(self, person_id: int, units: str) -> None:
        with self._pool.connection() as db:
            db.execute(
                """UPDATE person_widget SET settings = settings || jsonb_build_object('units', %s::text)
                   WHERE person_id = %s AND widget_key = 'weather'""",
                (units, person_id),
            )

    def new_api_key(self, person_id: int) -> str:
        """Replaces the person's API key, so the old one stops working."""
        key, key_hash = make_api_key()
        with self._pool.connection() as db:
            db.execute("UPDATE person SET api_key_hash = %s WHERE person_id = %s", (key_hash, person_id))
        return key

    def calendar_token(self, person_id: int) -> Optional[bytes]:
        """Their Google Calendar token, still encrypted. None if it isn't connected."""
        with self._pool.connection() as db:
            row = db.execute("SELECT refresh_token FROM google_calendar WHERE person_id = %s", (person_id,)).fetchone()
        return bytes(row[0]) if row else None

    def save_calendar(self, person_id: int, sealed_token: bytes) -> None:
        with self._pool.connection() as db:
            db.execute(
                """INSERT INTO google_calendar (person_id, refresh_token) VALUES (%s, %s)
                   ON CONFLICT (person_id) DO UPDATE
                   SET refresh_token = EXCLUDED.refresh_token, connected_at = now()""",
                (person_id, sealed_token),
            )

    def forget_calendar(self, person_id: int) -> None:
        with self._pool.connection() as db:
            db.execute("DELETE FROM google_calendar WHERE person_id = %s", (person_id,))

    def delete_person(self, person_id: int) -> None:
        """Their pictures, widgets and Brightspace login go too (ON DELETE CASCADE)."""
        with self._pool.connection() as db:
            db.execute("DELETE FROM person WHERE person_id = %s", (person_id,))
