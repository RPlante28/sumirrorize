# people and their widget layouts

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import asyncpg


@dataclass(frozen=True)
class Person:
    id: int
    name: str
    view_lock: bool = False


@dataclass(frozen=True)
class WidgetPlacement:
    key: str
    name: str
    x: float
    y: float
    w: float
    h: float
    settings: dict[str, Any]


class Store(Protocol):
    async def person(self, person_id: int) -> Optional[Person]: ...
    async def enabled_widgets(self, person_id: int) -> list[WidgetPlacement]: ...
    async def google_token(self, person_id: int) -> Optional[bytes]: ...
    async def weather_units(self, person_id: int) -> str: ...


class PostgresStore:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> "PostgresStore":
        async def init(connection: asyncpg.Connection) -> None:
            await connection.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")

        return cls(await asyncpg.create_pool(url, min_size=1, max_size=5, init=init))

    async def close(self) -> None:
        await self._pool.close()

    async def person(self, person_id: int) -> Optional[Person]:
        row = await self._pool.fetchrow(
            "SELECT person_id, display_name, view_lock FROM person WHERE person_id = $1", person_id
        )
        return Person(row["person_id"], row["display_name"], row["view_lock"]) if row else None

    async def google_token(self, person_id: int) -> Optional[bytes]:
        """Their Google Calendar token as the app saved it (encrypted), or None if it isn't connected."""
        return await self._pool.fetchval("SELECT refresh_token FROM google_calendar WHERE person_id = $1", person_id)

    async def enabled_widgets(self, person_id: int) -> list[WidgetPlacement]:
        rows = await self._pool.fetch(
            """SELECT pw.widget_key, w.name, pw.x, pw.y, pw.w, pw.h, pw.settings
               FROM person_widget pw JOIN widget w USING (widget_key)
               WHERE pw.person_id = $1 AND pw.enabled
               ORDER BY pw.y, pw.x""",
            person_id,
        )
        return [
            WidgetPlacement(r["widget_key"], r["name"], r["x"], r["y"], r["w"], r["h"], r["settings"])
            for r in rows
        ]

    async def weather_units(self, person_id: int) -> str:
        value = await self._pool.fetchval(
            "SELECT settings->>'units' FROM person_widget WHERE person_id = $1 AND widget_key = 'weather'",
            person_id,
        )
        return value if value in {"imperial", "metric"} else "imperial"
