"""
The blink check: before the mirror opens for someone, the server has to see them blink. A photo
of a person can be recognized, but it can't blink. (A video of them blinking still could.)

The faces service says how open the recognized person's eyes are in each camera frame. A blink
is three steps: eyes open, then closed, then open again, all on frames recognized as the same
person. How far someone has got travels with the page as a signed token, which it sends back
with its next frame, so the server keeps nothing between frames.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .passes import Signer

# How long after one step the next frame may arrive. The page sends several frames a second.
STEP_TIMEOUT = 2.5
# Eyes shut for longer than this isn't a blink (e.g. a photo of someone with their eyes closed).
MAX_CLOSED = 2.0


@dataclass(frozen=True)
class Progress:
    person_id: int
    closed_since: float   # when their eyes were first seen closed; 0 while still waiting for that
    seen: float           # when this step was last confirmed


class BlinkCheck:
    def __init__(self, signer: Signer, open_at: float, closed_at: float):
        self._signer = signer
        self._open_at = open_at       # eyes count as open at or above this (0-1)
        self._closed_at = closed_at   # and as closed at or below this; in between is ignored

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
        """
        Takes one frame in which `person_id` was recognized, with the token from their previous
        frame. Returns (blinked, the token to send with the next frame).
        """
        progress = self._read(token, person_id, now)
        is_open = eyes_open is not None and eyes_open >= self._open_at
        is_closed = eyes_open is not None and eyes_open <= self._closed_at

        if progress and progress.closed_since:
            if now - progress.closed_since > MAX_CLOSED:
                progress = None   # shut for too long: start over
            elif is_open:
                return True, None
            else:
                return False, self._write(Progress(person_id, progress.closed_since, now))

        if is_open:
            return False, self._write(Progress(person_id, 0, now))
        if is_closed and progress:
            return False, self._write(Progress(person_id, now, now))
        # Eyes can't be read or are half open: nothing changes, and the step's clock keeps running.
        return False, token if progress else None
