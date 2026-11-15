# Limits how often one address can ask "who is this?", so nobody can try lots of photos fast.

from __future__ import annotations

import time
from fastapi import Request


def client_address(request: Request) -> str:
    """Behind Cloudflare the real address is in CF-Connecting-IP."""
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


class RateLimiter:
    """Token bucket per address."""

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
        if len(self._buckets) > 10_000:  # forget old ones
            self._buckets = {a: b for a, b in self._buckets.items() if now - b[1] < 60}
        return allowed
