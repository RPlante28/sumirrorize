# keeps the last good result of a fetch so the weather APIs aren't hit on every request

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Generic, Optional, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


class Unavailable(Exception):
    """No data at all yet."""


@dataclass(frozen=True)
class Result(Generic[T]):
    value: T
    fetched_at: datetime
    stale: bool  # old data, the latest fetch failed


class Cached(Generic[T]):
    """Refetches after `ttl` seconds. If that fails, keeps serving the old value and waits `retry_after`."""

    def __init__(self, name: str, fetch: Callable[[], Awaitable[T]], ttl: float, retry_after: float):
        self._name = name
        self._fetch = fetch
        self._ttl = ttl
        self._retry_after = retry_after
        self._value: Optional[T] = None
        self._fetched_at: Optional[datetime] = None
        self._fresh_until = 0.0
        self._next_try = 0.0
        self._last_fetch_failed = False
        self._lock = asyncio.Lock()

    async def get(self) -> Result[T]:
        # one fetch at a time, later requests wait and reuse it
        async with self._lock:
            now = time.monotonic()
            if now >= self._fresh_until and now >= self._next_try:
                try:
                    self._value = await self._fetch()
                    self._fetched_at = datetime.now(timezone.utc)
                    self._fresh_until = now + self._ttl
                    self._last_fetch_failed = False
                except Exception as error:  # network, bad status, weird data
                    logger.warning("Fetching %s failed: %r", self._name, error)
                    self._next_try = now + self._retry_after
                    self._last_fetch_failed = True

            if self._value is None or self._fetched_at is None:
                raise Unavailable(self._name)
            return Result(self._value, self._fetched_at, stale=self._last_fetch_failed)
