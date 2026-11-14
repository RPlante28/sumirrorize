# The `weather` branch

This branch does three things:

1. **New folder layout.** Services are grouped by role, so it's clear where everything lives:
   ```
   backends/   d3l (moved here from /d3l), weather, mirror, and later app
   frontends/  mirror, and later app
   db/         unchanged
   ```
   [backends/README.md](backends/README.md) lists every service and how they connect.
2. **Weather service** (`backends/weather`), built from StormWatch's weather code. It gives the
   mirror's weather widget current conditions, today's high/low, the next 12 hours, and NWS
   alerts. Details: [backends/weather/README.md](backends/weather/README.md).
3. **A working mirror** at **https://sumirrorize.marist.dev**: a backend (`backends/mirror`)
   that gathers a person's widgets and data, and the display (`frontends/mirror`). See
   [the mirror section](#the-mirror) below.

## What changed for teammates

- **d3l moved** from `d3l/` to `backends/d3l/`. Move your `d3l/.env` along with it.
  `docker compose --profile d3l up` now reads `backends/d3l/.env`.
- **`docker compose up -d` now also starts weather** on `http://localhost:3200`, next to the
  database. It needs no setup; the location defaults to Marist.
- **Face recognition:** `scripts/mirror.py` on the `face-recog` branch belongs in
  `backends/mirror/` once it becomes the mirror backend.
- **Units setting:** the weather widget's per-person setting is `units` in
  `person_widget.settings`, either `"imperial"` (the default) or `"metric"`. The mirror backend
  passes it as `GET /weather?units=...`.

## Server

| Container | Reachable at |
|---|---|
| `sumirrorize-weather` | `http://sumirrorize-weather:3200`, on the `sumirrorize` network only (no public address) |

The location is set in `/opt/containers/sumirrorize/docker-compose.yml` (Marist College).
That stack now builds d3l from `backends/d3l`, so this branch needs to be checked out (or
merged) before the next d3l rebuild.

## Tested

- **Automated tests:** 10 tests against fake weather APIs (`backends/weather/tests`), covering
  °F/°C conversion, the 12-hour window, alert order, caching, serving old data when a fetch
  fails, waiting before retrying, the 503 when there's no data, and weather still working
  without alerts.
- **Real APIs:** run against the real Open-Meteo and NWS for Poughkeepsie, locally, in Docker
  (read-only, non-root), and on the server.

## Drawbacks

- **US-only alerts.** NWS covers the US only; anywhere else, `alerts` is always empty.
- **One location.** The weather is for the mirror's spot. Showing a different city per person
  would need a city setting, plus a way to turn a city name into coordinates.
- **Unofficial free services.** Neither API has an uptime guarantee or a key. Caching keeps
  requests low, and old data is served if they go down.
- **Cache resets on restart.** It's in memory, so the first request after a restart waits on the
  weather APIs (about a second).
- **No icons.** The service returns WMO weather codes and descriptions; the mirror frontend picks
  the icons.

## The mirror

The mirror is a page showing one person's widgets, each at the position they saved, with live
data: clock, greeting, weather, a summary of the day, their Brightspace calendar, their
assignments (overdue first), and recent course announcements. Each widget is a bordered card,
lists show only whole items plus "+N more", and the default layout keeps the middle of the
mirror clear for your reflection. Details: [backends/mirror/README.md](backends/mirror/README.md)
and [frontends/mirror/README.md](frontends/mirror/README.md).

**Using it:**
1. Open `https://sumirrorize.marist.dev/#key=<MIRROR_KEY>` once on the mirror screen. The key is
   in `/opt/containers/sumirrorize/.env`, and the page remembers it.
2. Pick who's at the mirror. This stands in for face recognition.
3. To switch person, move the mouse and click "Switch person", or press Esc.

**Locally:** run `db/init/004_announcements_and_layout.sql` on your database if it existed
before this branch (see `db/README.md`). Then `cp backends/mirror/.env.example backends/mirror/.env`,
fill it in, and run
`docker compose --profile d3l --profile mirror up -d --build` and open `http://localhost:8080`.

**Server:**

| Container | What | Reachable at |
|---|---|---|
| `sumirrorize-mirror-web` | The page (nginx), forwards `/api/` to the backend | `https://sumirrorize.marist.dev` |
| `sumirrorize-mirror` | The mirror backend | `sumirrorize` network only |

**Tested:**
- **Automated:** 12 tests against a fake database and fake d3l and weather services. They cover
  the mirror key, filtering assignments and announcements (hidden, unpublished, old, scheduled,
  ended courses, posts shared between courses), each source being fetched once and only when
  needed, the units setting, one failing source not affecting other widgets, the summary
  wording, and shortening course names.
- **Live:** on the server with the friend's real Brightspace data. All seven widgets load
  through the public address in about a second (announcements check each course). The page was checked in a real browser at
  1080p and 720p, including remembering the person after a reload.

### Mirror drawbacks

- **No face recognition yet.** The mirror shows a person picker. The `face-recog` work should
  produce a `person_id` in `backends/mirror`, and the rest stays the same.
- **One key for the whole mirror.** It's stored in the browser on the mirror screen, and anyone
  with it can see every person's mirror. Treat it like a password, and change `MIRROR_KEY` (then
  restart `sumirrorize-mirror`) if it leaks. Putting Cloudflare Access in front of
  `sumirrorize.marist.dev` would add a proper login.
- **The calendar is Brightspace's calendar.** It mostly holds due dates and course events, not
  class times; Marist keeps class schedules elsewhere.
- **The summary is fill-in-the-blank, not AI.** It's built from counts and the weather.
- **Default layout until the app exists.** Widgets sit where the database's default layout
  puts them until the app lets people move them. The new layout and the announcements widget
  come from `db/init/004_announcements_and_layout.sql`. Fresh databases get it automatically.
  Existing ones (including teammates' local copies) need it run by hand; see `db/README.md`.
  People who already existed keep their old layout. On the server, the test person was moved
  to the new layout by hand.
- **Announcements cost a request per course.** About half a second for 27 courses, on every
  5-minute refresh.
- **5-minute refresh.** Brightspace and weather data refresh every 5 minutes, so a newly posted
  assignment can take that long to appear.
