# face pictures and fingerprints (the picture table)

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, Sequence

import asyncpg
import numpy as np


@dataclass(frozen=True)
class NewPicture:
    angle: str
    image: bytes
    mime_type: str
    fingerprint: np.ndarray


@dataclass(frozen=True)
class SavedPicture:
    angle: str
    created_at: datetime


@dataclass(frozen=True)
class Match:
    person_id: int
    similarity: float


class Store(Protocol):
    async def person_exists(self, person_id: int) -> bool: ...
    async def saved_pictures(self, person_id: int) -> list[SavedPicture]: ...
    async def replace_pictures(self, person_id: int, pictures: Sequence[NewPicture]) -> None: ...
    async def delete_pictures(self, person_id: int) -> int: ...
    async def closest(self, fingerprint: np.ndarray) -> Optional[Match]: ...


def _vector(fingerprint: np.ndarray) -> str:
    """pgvector's text format, e.g. "[0.1,0.2]". Saves needing the pgvector package."""
    return "[" + ",".join(f"{v:.7g}" for v in fingerprint.tolist()) + "]"


class PostgresStore:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> "PostgresStore":
        return cls(await asyncpg.create_pool(url, min_size=1, max_size=5))

    async def close(self) -> None:
        await self._pool.close()

    async def person_exists(self, person_id: int) -> bool:
        return bool(await self._pool.fetchval("SELECT 1 FROM person WHERE person_id = $1", person_id))

    async def saved_pictures(self, person_id: int) -> list[SavedPicture]:
        rows = await self._pool.fetch(
            "SELECT angle, created_at FROM picture WHERE person_id = $1 ORDER BY pic_id", person_id)
        return [SavedPicture(r["angle"], r["created_at"]) for r in rows]

    async def replace_pictures(self, person_id: int, pictures: Sequence[NewPicture]) -> None:
        # one transaction, so the mirror never sees half an old set and half a new one
        async with self._pool.acquire() as connection, connection.transaction():
            await connection.execute("DELETE FROM picture WHERE person_id = $1", person_id)
            await connection.executemany(
                """INSERT INTO picture (person_id, angle, image, mime_type, face_encoding)
                   VALUES ($1, $2, $3, $4, $5::vector)""",
                [(person_id, p.angle, p.image, p.mime_type, _vector(p.fingerprint)) for p in pictures],
            )

    async def delete_pictures(self, person_id: int) -> int:
        result = await self._pool.execute("DELETE FROM picture WHERE person_id = $1", person_id)
        return int(result.split()[-1])

    async def closest(self, fingerprint: np.ndarray) -> Optional[Match]:
        # <=> is cosine distance, i.e. 1 - similarity
        row = await self._pool.fetchrow(
            """SELECT person_id, 1 - (face_encoding <=> $1::vector) AS similarity
               FROM picture WHERE face_encoding IS NOT NULL
               ORDER BY face_encoding <=> $1::vector LIMIT 1""",
            _vector(fingerprint),
        )
        return Match(row["person_id"], float(row["similarity"])) if row else None
