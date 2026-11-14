# weather

Weather for the mirror's location: current conditions, today's high/low, the next 12 hours,
and active National Weather Service alerts. Adapted from StormWatch (`~/projects/StormWatch`):
the Open-Meteo and NWS code came over, and the terminal UI, GPS and storm-risk parts were dropped.

- **Data:** [Open-Meteo](https://open-meteo.com) for conditions and forecast, and the
  [National Weather Service](https://www.weather.gov/documentation/services-web-api) for alerts.
  Both are free with no API key. NWS alerts only cover the US.
- **Location:** the weather is for where the mirror is, set once in config, not per person.
- **No login.** The data isn't personal, so there's no API key. On the server it's only reachable
  on the internal `sumirrorize` network, and only the mirror backend should call it.

## Running it

From the repo root, `docker compose up -d` starts it with the database, on
`http://localhost:3200`. Or directly:

```bash
cd backends/weather
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env && set -a && . ./.env && set +a
.venv/bin/uvicorn --factory app.main:create_app --port 3200 --reload
.venv/bin/python -m pytest      # tests, against fake weather APIs
```

| Setting | What |
|---|---|
| `WEATHER_LATITUDE`, `WEATHER_LONGITUDE` | Where the mirror is (required). Default in compose: Marist College |
| `WEATHER_LABEL` | Place name shown with the weather, e.g. `Poughkeepsie, NY` (optional) |

## `GET /weather?units=imperial`

`units` is `imperial` (default; °F, mph) or `metric` (°C, km/h). Each person picks theirs in
their weather widget's settings, e.g. `person_widget.settings = {"units": "metric"}`. The mirror
backend passes that setting along, using `imperial` if it isn't set.

```json
{
  "location": { "label": "Poughkeepsie, NY", "latitude": 41.7225, "longitude": -73.9343, "timezone": "America/New_York" },
  "units": { "temperature": "°F", "speed": "mph" },
  "current": {
    "temperature": 41.7, "feelsLike": 33.4, "humidity": 65, "windSpeed": 10.0, "windGusts": 19.9,
    "windDirection": "NW", "description": "Overcast", "weatherCode": 3, "isDay": true
  },
  "today": { "high": 44.4, "low": 34.9, "precipitationChance": 12,
             "sunrise": "2026-11-14T06:43:00-05:00", "sunset": "2026-11-14T16:36:00-05:00" },
  "hourly": [
    { "time": "2026-11-14T15:00:00-05:00", "temperature": 41.9, "precipitationChance": 2,
      "description": "Overcast", "weatherCode": 3, "isDay": true }
  ],
  "alerts": [
    { "event": "Winter Storm Warning", "headline": "...", "severity": "Severe", "urgency": "Expected",
      "area": "Dutchess", "starts": "...", "ends": "...", "description": "...", "instruction": "..." }
  ],
  "updatedAt": "2026-11-14T20:27:28Z",
  "stale": false
}
```

- **`hourly`** has 12 entries, starting with the current hour.
- **Weather codes:** `weatherCode` is a [WMO code](https://open-meteo.com/en/docs#weather_variable_documentation)
  (0 = clear, 61 = light rain, ...). Use it with `isDay` to pick an icon. `description` is the
  same thing in words.
- **Alerts** are sorted most serious first. `[]` means there are no alerts right now; `null` means
  alerts couldn't be fetched.
- **Stale data:** `stale: true` means the latest fetch failed and this is older data. The weather
  APIs are asked at most every 10 minutes for the forecast and every 2 minutes for alerts.
  After a failure, the service waits 30 seconds before trying again and keeps serving the old data
  meanwhile.
- **Errors:** if no forecast has ever been fetched, you get `503`:
  `{"error": "...", "code": "weather_unavailable"}`.

`GET /health` returns `{"ok": true}`.

## Files

| File | What |
|---|---|
| `app/main.py` | Routes, and turning fetched data into the response |
| `app/open_meteo.py` | Conditions, today, and the next 12 hours (from StormWatch) |
| `app/nws.py` | Weather alerts (from StormWatch) |
| `app/cache.py` | Keeps the last good data, with the refresh and retry timing |
| `app/units.py` | °C/°F, km/h/mph, compass directions |
| `app/models.py` | The response format |
| `tests/` | Tests against fake weather APIs |
