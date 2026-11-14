"""
Limits how often one visitor can ask "who is this?". The mirror page asks twice a second;
much more than that from one address is someone trying lots of photos.
"""

from __future__ import annotations

import time
from fastapi import Request


def client_address(request: Request) -> str:
    """The visitor's address. Behind Cloudflare the real one is in CF-Connecting-IP."""
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


class RateLimiter:
    """Token bucket per address: `burst` requests at once, refilling at `per_second`."""

    def __init__(self, per_second: float, burst: int):
        self._rate = per_second
        self._burst = burst
        self._buckets: dict[str, tuple[float, float]] = {}  # address -> (tokens, last seen)

    def allow(self, address: str) -> bool:
        now = time.monotonic()
        tokens, last = self._buckets.get(address, (self._burst, now))
        tokens = min(self._burst, tokens + (now - last) * self._rate)
        allowed = tokens >= 1
        self._buckets[address] = (tokens - 1 if allowed else tokens, now)
        if len(self._buckets) > 10_000:  # forget visitors who left long ago
            self._buckets = {a: b for a, b in self._buckets.items() if now - b[1] < 60}
        return allowed
