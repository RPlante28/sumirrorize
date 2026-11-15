# mirror (backend)

Works out who's at the mirror and gathers everything their mirror shows: their enabled widgets,
where they placed them, and each widget's data from d3l (Brightspace) and the weather service.

**Your face is the key, and it has to blink.** The mirror page
([`frontends/mirror`](../../frontends/mirror/README.md)) sends camera frames to `/api/identify`.
When the [faces service](../faces/README.md) recognizes someone, the backend waits to see them
blink, so a photo of them isn't enough. Then the answer includes a short-lived *pass*, and only
that pass can load their data from `/api/mirror`. There's no other way to get a person's data
from here: no key, no list of people, no lookups by ID.

## Running it

From the repo root (needs `FACES_API_KEY` in `.env`):

```bash
cp backends/mirror/.env.example backends/mirror/.env   # set D3L_SERVICE_KEY
docker compose --profile d3l --profile mirror up -d --build
# open http://localhost:8080 and allow the camera
```

Tests (against a fake database and fake d3l, weather and faces services):

```bash
cd backends/mirror
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

| Setting | What |
|---|---|
| `D3L_SERVICE_KEY` | d3l's `SERVICE_API_KEY`, for reading any person's Brightspace data |
| `FACES_API_KEY` | The faces service's key |
| `DATABASE_URL`, `D3L_URL`, `WEATHER_URL`, `FACES_URL` | Where the other parts are (compose fills these in) |
| `MIRROR_TIMEZONE` | Where the mirror is, for what "today" means. Default `America/New_York` |
| `MIRROR_EYES_OPEN_AT`, `MIRROR_EYES_CLOSED_AT` | The blink check's cutoffs on the faces service's 0–1 eye score: open at or above the first (default `0.7`), closed at or below the second (default `0.45`). Raise the second if real blinks are being missed; lower it if photos get in |

## API

Errors look like `{"error": "...", "code": "..."}`.

### `POST /api/identify`

The body is one camera frame (`Content-Type: image/jpeg`, PNG or WebP, under 2 MB).

Recognized, but not let in yet:

```json
{ "faces": 1, "person": { "id": 3, "name": "Alex Smith" },
  "pass": null, "expiresAt": null, "blink": "Ymxpbms6My8w..." }
```

After they blink:

```json
{ "faces": 1, "person": { "id": 3, "name": "Alex Smith" },
  "pass": "cGFzczozLjE3OTQ...", "expiresAt": "2026-11-14T22:10:00+00:00", "blink": null }
```

- **Nobody recognized:** `person`, `pass`, `expiresAt` and `blink` are `null`. `faces` is how
  many faces were in the frame, so the page can tell "a stranger is here" from "nobody is here".
- **The blink check:** a blink is the recognized person's eyes seen open, then closed, then open
  again, on frames at most 2.5 seconds apart, with the eyes shut for no more than 2 seconds.
  Every frame along the way has to be recognized as the same person. `blink` is how far they've
  got, signed by the server: send it back with the next frame in an `X-Blink` header. The server
  keeps nothing between frames.
- **Staying in:** send the current pass (`Authorization: Bearer <pass>`) with each frame. While
  the same person is recognized, it's swapped for a fresh one without another blink.
- **Passes** last 2 minutes and are signed by the server, so they can't be forged or changed to
  another person. Restarting the backend cancels all passes and blink progress; the person just
  blinks again.
- **Rate limit:** 40 requests at once per address, refilling at 12 per second. Beyond that you
  get `429 rate_limited`. A mirror sends 2 per second, and up to 10 per second for the moment
  it's waiting for a blink. Everyone on one wifi network usually shares an address.
- **Errors:** `415`/`400 bad_image`, `413 too_large`, `503 faces_unavailable`.

### `GET /api/mirror`

Send `Authorization: Bearer <pass>`. Without a valid pass you get `401 pass_expired`.

```json
{
  "person": { "id": 3, "name": "Alex Smith" },
  "timezone": "America/New_York",
  "generatedAt": "2026-11-14T20:51:00Z",
  "widgets": [
    { "key": "weather", "name": "Weather", "x": 0.70, "y": 0.03, "w": 0.28, "h": 0.30,
      "settings": {}, "data": { "...": "the weather service's response" }, "error": null },
    { "key": "calendar", "name": "Calendar", "x": 0.02, "y": 0.21, "w": 0.28, "h": 0.76,
      "settings": {}, "data": null,
      "error": { "code": "signin_required", "message": "Connect Brightspace in the app to see this" } }
  ]
}
```

Only enabled widgets are included. Each one's `data`:

| Widget | `data` |
|---|---|
| `clock` | `null` (the page uses its own clock) |
| `greeting` | `{ "name": "Alex" }`, the first word of their name |
| `weather` | The weather service's response, in the units from the widget's `settings.units` (`imperial` by default) |
| `calendar` | `{ "events": [{ "title", "course", "starts", "ends", "allDay", "location" }] }`: today through 6 days ahead, minus events that have ended |
| `assignments` | `{ "assignments": [{ "name", "course", "due", "overdue" }] }`: overdue work first, then open upcoming work, soonest first, at most 8 |
| `announcements` | `{ "announcements": [{ "title", "course", "posted", "text" }] }`: the last 14 days across active courses, newest first, at most 8. `text` is the start of the body on one line. A post made to several courses appears once, with `course` like `"MATH 343L, MATH 310L"` |
| `summary` | `{ "text": "Nothing on your calendar today. 1 assignment due in the next 3 days, 2 overdue. 3 new announcements since yesterday. Overcast, high of 44°F." }` |

- **Errors stay contained.** A failing source only affects its own widgets: `data` becomes
  `null` and `error` explains why. The summary leaves out whatever it couldn't get. This covers
  surprises too: if Brightspace sends an item in a shape the code didn't expect, the widgets
  that needed it say `unavailable`, the problem is logged, and the rest of the mirror shows.
- **Error codes:** `signin_required` (connect Brightspace in the app), `brightspace_unavailable`,
  `weather_unavailable`, `unavailable`.
- **Fetching:** each source is fetched at most once per request, and only if an enabled widget
  needs it. The course list feeds both assignments and announcements, and is fetched once.
- **Announcements are per course in Brightspace,** so they take one request per active course
  (8 at a time). Courses whose access has ended are refused by Brightspace (403) and skipped.
  For a student with 27 courses this takes about half a second.
- **Course names:** Marist's (`CMPT_435L_112_26F ALGORITHM ANALYSISDESIGN`) are shortened to
  `CMPT 435L`. Names in other formats pass through unchanged.

## Files

| File | What |
|---|---|
| `app/main.py` | Routes: recognizing faces, handing out passes, loading a person's mirror |
| `app/blink.py` | The blink check: open, closed, open |
| `app/passes.py` | Signing the passes and the blink progress |
| `app/ratelimit.py` | Limiting how fast one visitor can send frames |
| `app/widgets.py` | Which data each widget needs, building it, and the day summary |
| `app/sources.py` | Calling d3l, weather and faces, and trimming Brightspace's data |
| `app/store.py` | Reading people and widget layouts from the database |
| `tests/` | Tests against a fake database and fake backends |
