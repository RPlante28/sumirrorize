# mirror (backend)

Gathers everything one person's mirror shows: their enabled widgets, where they placed them,
and each widget's data from d3l (Brightspace) and the weather service. The mirror page
([`frontends/mirror`](../../frontends/mirror/README.md)) makes one request and draws the result.

**Who's at the mirror:** for now the mirror page picks the person from a list. Face recognition
(the `face-recog` branch) should replace that step by working out a `person_id`. Everything after
that stays the same.

## Running it

From the repo root:

```bash
cp backends/mirror/.env.example backends/mirror/.env   # set MIRROR_KEY and D3L_SERVICE_KEY
docker compose --profile d3l --profile mirror up -d --build
# open http://localhost:8080/#key=<MIRROR_KEY>
```

Tests (against a fake database and fake d3l/weather):

```bash
cd backends/mirror
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

| Setting | What |
|---|---|
| `MIRROR_KEY` | What the mirror page must send. Everything here is personal data and the page is public |
| `D3L_SERVICE_KEY` | d3l's `SERVICE_API_KEY`, for reading any person's Brightspace data |
| `DATABASE_URL`, `D3L_URL`, `WEATHER_URL` | Where the other parts are (compose fills these in) |
| `MIRROR_TIMEZONE` | Where the mirror is, for what "today" means. Default `America/New_York` |

## API

Every route except `/api/health` needs `Authorization: Bearer <MIRROR_KEY>`. Errors look like
`{"error": "...", "code": "..."}`, e.g. `bad_mirror_key` (401) or `no_such_person` (404).

### `GET /api/people`

Everyone the mirror knows: `[{"id": 3, "name": "Alex Smith"}]`.

### `GET /api/people/{id}/mirror`

```json
{
  "person": { "id": 3, "name": "Alex Smith" },
  "timezone": "America/New_York",
  "generatedAt": "2026-11-14T20:51:00Z",
  "widgets": [
    { "key": "weather", "name": "Weather", "x": 0.72, "y": 0.03, "w": 0.25, "h": 0.15,
      "settings": {}, "data": { "...": "the weather service's response" }, "error": null },
    { "key": "calendar", "name": "Calendar", "x": 0.03, "y": 0.62, "w": 0.45, "h": 0.35,
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
  `null` and `error` explains why. The summary leaves out whatever it couldn't get.
- **Error codes:** `signin_required` (connect Brightspace in the app), `brightspace_unavailable`,
  `weather_unavailable`.
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
| `app/main.py` | Routes and the mirror key check |
| `app/widgets.py` | Which data each widget needs, building it, and the day summary |
| `app/sources.py` | Calling d3l and weather, and trimming Brightspace's data |
| `app/store.py` | Reading people and widget layouts from the database |
| `tests/` | Tests against a fake database and fake backends |
