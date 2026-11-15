# Blink check: the mirror only opens once the server has seen the person blink, so a photo of
# them isn't enough (a video still would be).
#
# faces says how open the eyes are in each frame. A blink is open, closed, open, all on frames
# recognized as the same person. Progress travels with the page as a signed token, so nothing
# is kept here between frames.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .passes import Signer

# max time between two steps
STEP_TIMEOUT = 2.5
# eyes shut longer than this isn't a blink (e.g. a photo with closed eyes)
MAX_CLOSED = 2.0


@dataclass(frozen=True)
class Progress:
    person_id: int
    closed_since: float  # when the eyes were first seen closed, 0 = not yet
    seen: float  # last time this step was confirmed


class BlinkCheck:
    def __init__(self, signer: Signer, open_at: float, closed_at: float):
        self._signer = signer
        self._open_at = open_at  # open at or above this (0-1)
        self._closed_at = closed_at  # closed at or below this

    def _write(self, progress: Progress) -> str:
        return self._signer.sign("blink", f"{progress.person_id}/{progress.closed_since!r}/{progress.seen!r}")

    def _read(self, token: Optional[str], person_id: int, now: float) -> Optional[Progress]:
        text = self._signer.read("blink", token)
        if text is None:
            return None
        person, closed_since, seen = text.split("/")
        progress = Progress(int(person), float(closed_since), float(seen))
        if progress.person_id != person_id or not 0 <= now - progress.seen <= STEP_TIMEOUT:
            return None
        return progress

    def step(self, token: Optional[str], person_id: int, eyes_open: Optional[float],
             now: float) -> tuple[bool, Optional[str]]:
        """One recognized frame plus the token from the frame before -> (blinked, next token)."""
        progress = self._read(token, person_id, now)
        is_open = eyes_open is not None and eyes_open >= self._open_at
        is_closed = eyes_open is not None and eyes_open <= self._closed_at

        if progress and progress.closed_since:
            if now - progress.closed_since > MAX_CLOSED:
                progress = None  # shut too long, start over
            elif is_open:
                return True, None
            else:
                return False, self._write(Progress(person_id, progress.closed_since, now))

        if is_open:
            return False, self._write(Progress(person_id, 0, now))
        if is_closed and progress:
            return False, self._write(Progress(person_id, now, now))
        # eyes unreadable or half open: nothing changes and the clock keeps running
        return False, token if progress else None
