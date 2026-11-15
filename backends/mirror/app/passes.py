"""
Signed tokens the mirror page holds for a short while. They're signed with a secret made at
startup, so they can't be forged and a restart cancels them all (the mirror simply earns new ones).

A pass is proof that the server recognized someone's face and saw them blink a moment ago. The
page needs it to load their data, and trades it for a fresh one each time it recognizes them again.
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


class Signer:
    """Signs short pieces of text. Each token says what `kind` it is, so one kind can't pass as another."""

    def __init__(self, secret: Optional[bytes] = None):
        self._secret = secret or os.urandom(32)

    def _signature(self, body: bytes) -> bytes:
        return hmac.new(self._secret, body, hashlib.sha256).digest()

    def sign(self, kind: str, text: str) -> str:
        body = f"{kind}:{text}".encode()
        return f"{_b64(body)}.{_b64(self._signature(body))}"

    def read(self, kind: str, token: Optional[str]) -> Optional[str]:
        """The text inside a token of this kind, or None if it's missing, forged or malformed."""
        try:
            body_part, signature_part = (token or "").split(".")
            body, signature = _unb64(body_part), _unb64(signature_part)
            if not hmac.compare_digest(signature, self._signature(body)):
                return None
            found_kind, _, text = body.decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return None
        return text if found_kind == kind else None


class Passes:
    def __init__(self, signer: Signer, lifetime_seconds: float):
        self._signer = signer
        self._lifetime = lifetime_seconds

    def issue(self, person_id: int) -> tuple[str, datetime]:
        expires = int(time.time() + self._lifetime)
        return self._signer.sign("pass", f"{person_id}.{expires}"), datetime.fromtimestamp(expires, timezone.utc)

    def check(self, token: Optional[str]) -> Optional[int]:
        """The person the pass is for, or None if it's forged, malformed or expired."""
        text = self._signer.read("pass", token)
        if text is None:
            return None
        person_id, expires = (int(part) for part in text.split("."))
        return person_id if time.time() < expires else None
