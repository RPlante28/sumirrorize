# Encrypts Google refresh tokens before they go in the database. The mirror backend has the same
# key (GOOGLE_TOKEN_KEY) and reads them back.

from __future__ import annotations

from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class Vault:
    def __init__(self, key: str):
        try:
            self._fernet = Fernet(key.encode())
        except ValueError:
            raise RuntimeError("GOOGLE_TOKEN_KEY isn't a valid key (see .env.example)") from None

    def seal(self, person_id: int, token: str) -> bytes:
        # the person's ID goes in too, so a token copied into someone else's row won't open
        return self._fernet.encrypt(f"{person_id}:{token}".encode())

    def unseal(self, person_id: int, sealed: bytes) -> Optional[str]:
        try:
            owner, _, token = self._fernet.decrypt(bytes(sealed)).decode().partition(":")
        except InvalidToken:
            return None
        return token if owner == str(person_id) else None
