# Google Calendar events for the calendar widget. People connect their calendar in the sign-up
# app, which saves an encrypted refresh token. Here it's swapped for a short-lived access token
# (kept in memory until it runs out) and used to read their main calendar.

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .config import Settings
from .sources import Event, SourceError
from .store import Store

TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
MAX_EVENTS = 50


class GoogleCalendar:
    def __init__(self, client: httpx.AsyncClient, store: Store, settings: Settings):
        self._client = client
        self._store = store
        self._client_id = settings.google_client_id
        self._client_secret = settings.google_client_secret
        self._fernet = Fernet(settings.google_token_key.encode()) if settings.google_token_key else None
        self._zone = settings.timezone
        self._access: dict[int, tuple[str, float]] = {}   # person -> (access token, when it runs out)

    @property
    def _set_up(self) -> bool:
        return bool(self._fernet and self._client_id and self._client_secret)

    async def events(self, person_id: int, start: datetime, end: datetime) -> Optional[list[Event]]:
        """Their events overlapping [start, end) that haven't finished. None if they haven't connected a calendar."""
        if not self._set_up:
            return None
        sealed = await self._store.google_token(person_id)
        if sealed is None:
            return None
        token = await self._access_token(person_id, sealed)
        try:
            response = await self._client.get(
                EVENTS_URL,
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "timeMin": start.isoformat(), "timeMax": end.isoformat(),
                    "singleEvents": "true",   # repeating events come as one item per occurrence
                    "orderBy": "startTime", "maxResults": str(MAX_EVENTS),
                },
            )
        except httpx.HTTPError as error:
            raise SourceError("google_unavailable", f"Couldn't reach Google Calendar: {error!r}") from error
        if response.status_code == 401:
            self._access.pop(person_id, None)
        if response.is_error:
            raise SourceError("google_unavailable", f"Google Calendar returned {response.status_code}: {_reason(response)}")

        now = datetime.now(timezone.utc)
        found = [self._event(item) for item in response.json().get("items", []) if _going(item)]
        return sorted((e for e in found if e.ends >= now), key=lambda e: e.starts)

    async def _access_token(self, person_id: int, sealed: bytes) -> str:
        cached = self._access.get(person_id)
        if cached and time.monotonic() < cached[1]:
            return cached[0]
        try:
            owner, _, refresh_token = self._fernet.decrypt(bytes(sealed)).decode().partition(":")
        except InvalidToken:
            owner = None
        if owner != str(person_id):
            raise SourceError("google_unavailable", "The saved Google Calendar token can't be read")
        try:
            response = await self._client.post(TOKEN_URL, data={
                "grant_type": "refresh_token", "refresh_token": refresh_token,
                "client_id": self._client_id, "client_secret": self._client_secret,
            })
        except httpx.HTTPError as error:
            raise SourceError("google_unavailable", f"Couldn't reach Google: {error!r}") from error
        if response.is_error:
            # invalid_grant here means they took the access away in their Google account
            raise SourceError("google_unavailable",
                              f"Google wouldn't renew calendar access ({response.status_code}: {_reason(response)})")
        body = response.json()
        # a minute early, so it doesn't run out mid-request
        self._access[person_id] = (body["access_token"], time.monotonic() + body.get("expires_in", 3600) - 60)
        return body["access_token"]

    def _event(self, item: dict[str, Any]) -> Event:
        all_day = "date" in item["start"]
        return Event(
            title=item.get("summary") or "(no title)",
            course=None,
            starts=self._when(item["start"]),
            ends=self._when(item["end"]),
            all_day=all_day,
            location=item.get("location") or None,
        )

    def _when(self, moment: dict[str, str]) -> datetime:
        if "dateTime" in moment:
            return datetime.fromisoformat(moment["dateTime"].replace("Z", "+00:00"))
        # all-day events only have a date: midnight where the mirror is
        return datetime.combine(date.fromisoformat(moment["date"]), datetime.min.time(), tzinfo=self._zone)


def _reason(response: httpx.Response) -> str:
    """Google's own explanation of an error, for the log (e.g. the Calendar API isn't enabled)."""
    try:
        error = response.json().get("error")
    except ValueError:
        return "no details"
    if isinstance(error, dict):   # the Calendar API nests it, the token endpoint doesn't
        return str(error.get("message", "no details"))[:200]
    return str(response.json().get("error_description") or error or "no details")[:200]


def _going(item: dict[str, Any]) -> bool:
    """False for cancelled events and invitations they turned down."""
    if item.get("status") == "cancelled" or "start" not in item or "end" not in item:
        return False
    me = next((a for a in item.get("attendees", []) if a.get("self")), None)
    return not (me and me.get("responseStatus") == "declined")
