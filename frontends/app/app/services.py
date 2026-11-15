"""The two internal services the app calls: d3l (Brightspace) and faces."""

from __future__ import annotations

from typing import Any

import httpx


class ServiceError(Exception):
    """A service said no, or couldn't be reached. Carries what to tell the browser."""

    def __init__(self, status: int, message: str, code: str, **extra: Any):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.extra = extra


def _send(client: httpx.Client, name: str, method: str, url: str, **kwargs: Any) -> httpx.Response:
    try:
        response = client.request(method, url, **kwargs)
    except httpx.HTTPError:
        raise ServiceError(503, f"Can't reach the {name} service, try again in a minute",
                           f"{name}_unavailable") from None
    if response.is_success:
        return response
    # Services answer errors with {"error": "...", "code": "...", ...anything else to pass on}.
    try:
        body = response.json()
        message, code = body.pop("error"), body.pop("code")
    except (ValueError, KeyError, AttributeError, TypeError):
        raise ServiceError(502, f"The {name} service had a problem, try again", f"{name}_error") from None
    raise ServiceError(response.status_code, message, code or f"{name}_error", **body)


class D3l:
    """Brightspace sign-in, as a trusted backend acting for one person."""

    def __init__(self, client: httpx.Client, base_url: str, service_key: str):
        self._client = client
        self._base_url = base_url
        self._service_key = service_key

    def _call(self, method: str, path: str, person_id: int) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._service_key}", "X-Person-Id": str(person_id)}
        return _send(self._client, "d3l", method, f"{self._base_url}{path}", headers=headers)

    def start_sign_in(self, person_id: int) -> dict[str, Any]:
        """`{"path": "/login/<one-time token>", "expiresAt": ...}`: the sign-in tab, on d3l."""
        return self._call("POST", "/login", person_id).json()

    def status(self, person_id: int) -> dict[str, Any]:
        """`{"signedIn": bool, "signedInAt": ..., "signingIn": bool}`"""
        return self._call("GET", "/session", person_id).json()

    def sign_out(self, person_id: int) -> None:
        self._call("DELETE", "/session", person_id)


class Faces:
    def __init__(self, client: httpx.Client, base_url: str, api_key: str):
        self._client = client
        self._base_url = base_url
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def saved(self, person_id: int) -> list[dict[str, Any]]:
        """The angles and dates of the person's saved pictures (not the pictures)."""
        url = f"{self._base_url}/people/{person_id}/faces"
        return _send(self._client, "faces", "GET", url, headers=self._headers).json()["pictures"]

    def save(self, person_id: int, pictures: list[dict[str, str]]) -> dict[str, Any]:
        """Replaces the person's pictures. A poor picture raises `poor_pictures` with which to retake."""
        url = f"{self._base_url}/people/{person_id}/faces"
        return _send(self._client, "faces", "PUT", url, headers=self._headers,
                     json={"pictures": pictures}).json()
