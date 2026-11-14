# The `weather` branch

This branch does two things:

1. **New folder layout.** Services are grouped by role, so it's clear where everything lives:
   ```
   backends/   d3l (moved here from /d3l), weather, and later mirror and app
   frontends/  later: mirror and app
   db/         unchanged
   ```
   [backends/README.md](backends/README.md) lists every service and how they connect.
2. **Weather service** (`backends/weather`), built from StormWatch's weather code. It gives the
   mirror's weather widget current conditions, today's high/low, the next 12 hours, and NWS
   alerts. Details: [backends/weather/README.md](backends/weather/README.md).

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
