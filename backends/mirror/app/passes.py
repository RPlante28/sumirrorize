"""
Short-lived passes: proof that the server recognized someone's face a moment ago. The mirror
page gets one each time it recognizes the person, and needs it to load their data. Passes are
signed with a secret made at startup, so they can't be forged and a restart cancels them all
(the mirror simply gets a new one on its next recognition).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from datetime import datetime, timezone
from typing import Optional


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Passes:
    def __init__(self, lifetime_seconds: float, secret: Optional[bytes] = None):
        self._lifetime = lifetime_seconds
        self._secret = secret or os.urandom(32)

    def _sign(self, body: bytes) -> bytes:
        return hmac.new(self._secret, body, hashlib.sha256).digest()

    def issue(self, person_id: int) -> tuple[str, datetime]:
        expires = int(time.time() + self._lifetime)
        body = f"{person_id}.{expires}".encode()
        return f"{_b64(body)}.{_b64(self._sign(body))}", datetime.fromtimestamp(expires, timezone.utc)

    def check(self, token: str) -> Optional[int]:
        """The person the pass is for, or None if it's forged, malformed or expired."""
        try:
            body_part, signature_part = token.split(".")
            body, signature = _unb64(body_part), _unb64(signature_part)
            if not hmac.compare_digest(signature, self._sign(body)):
                return None
            person_id, expires = (int(x) for x in body.decode().split("."))
        except (ValueError, UnicodeDecodeError):
            return None
        return person_id if time.time() < expires else None
