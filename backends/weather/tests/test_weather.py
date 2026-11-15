"""Runs the service against fake Open-Meteo and NWS APIs."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SETTINGS = Settings(latitude=41.7225, longitude=-73.9343, label="Poughkeepsie, NY")

OPEN_METEO = {
    "timezone": "America/New_York",
    "utc_offset_seconds": -18000,
    "current": {
        "time": "2026-11-14T15:15", "temperature_2m": 5.0, "apparent_temperature": 2.0,
        "relative_humidity_2m": 70, "weather_code": 61, "wind_speed_10m": 16.0934,
        "wind_direction_10m": 315, "wind_gusts_10m": 32.1868, "is_day": 1,
    },
    "hourly": {
        "time": [f"2026-11-14T{h:02d}:00" for h in range(15, 24)] + ["2026-11-15T00:00", "2026-11-15T01:00", "2026-11-15T02:00"],
        "temperature_2m": [5.0 - i * 0.5 for i in range(12)],
        "precipitation_probability": [40, 50, 60, None, 30, 20, 10, 10, 0, 0, 0, 0],
        "weather_code": [61, 61, 63, 3, 3, 2, 1, 0, 0, 0, 0, 0],
        "is_day": [1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "daily": {
        "time": ["2026-11-14"], "temperature_2m_max": [10.0], "temperature_2m_min": [0.0],
        "precipitation_probability_max": [60], "sunrise": ["2026-11-14T06:43"], "sunset": ["2026-11-14T16:36"],
    },
}


def nws_alert(event: str, severity: str, urgency: str) -> dict:
    return {"properties": {
        "event": event, "headline": f"{event} issued", "severity": severity, "urgency": urgency,
        "areaDesc": "Dutchess", "onset": "2026-11-14T18:00:00-05:00", "ends": None,
        "expires": "2026-11-15T06:00:00-05:00", "description": "Details.", "instruction": None,
    }}


NWS = {"features": [
    nws_alert("Wind Advisory", "Moderate", "Expected"),
    nws_alert("Winter Storm Warning", "Severe", "Expected"),
]}


class FakeApis:
    """Answers like the real APIs, counts calls, and can be told to fail."""

    def __init__(self):
        self.calls = {"forecast": 0, "alerts": 0}
        self.failing: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        name = "forecast" if request.url.host == "api.open-meteo.com" else "alerts"
        self.calls[name] += 1
        if name in self.failing:
            return httpx.Response(500, text="upstream down")
        if name == "forecast":
            assert request.url.params["forecast_hours"] == "12"
            return httpx.Response(200, json=OPEN_METEO)
        assert request.url.params["point"] == "41.7225,-73.9343"
        assert "Sumirrorize" in request.headers["user-agent"]
        return httpx.Response(200, json=NWS)


def client_for(fake: FakeApis, settings: Settings = SETTINGS) -> TestClient:
    return TestClient(create_app(settings, transport=httpx.MockTransport(fake)))


@pytest.fixture
def fake() -> FakeApis:
    return FakeApis()


def test_imperial_weather(fake):
    with client_for(fake) as client:
        body = client.get("/weather").json()

    assert body["location"] == {"label": "Poughkeepsie, NY", "latitude": 41.7225,
                                "longitude": -73.9343, "timezone": "America/New_York"}
    assert body["units"] == {"temperature": "F", "speed": "mph"}
    assert body["current"] == {
        "temperature": 41.0, "feelsLike": 35.6, "humidity": 70, "windSpeed": 10.0, "windGusts": 20.0,
        "windDirection": "NW", "description": "Light rain", "weatherCode": 61, "isDay": True,
    }
    assert body["today"] == {"high": 50.0, "low": 32.0, "precipitationChance": 60,
                             "sunrise": "2026-11-14T06:43:00-05:00", "sunset": "2026-11-14T16:36:00-05:00"}
    assert len(body["hourly"]) == 12
    assert body["hourly"][0] == {"time": "2026-11-14T15:00:00-05:00", "temperature": 41.0,
                                 "precipitationChance": 40, "description": "Light rain",
                                 "weatherCode": 61, "isDay": True}
    assert body["hourly"][3]["precipitationChance"] == 0  # missing value becomes 0
    assert body["stale"] is False


def test_alerts_most_serious_first(fake):
    with client_for(fake) as client:
        alerts = client.get("/weather").json()["alerts"]

    assert [a["event"] for a in alerts] == ["Winter Storm Warning", "Wind Advisory"]
    assert alerts[0]["starts"] == "2026-11-14T18:00:00-05:00"
    assert alerts[0]["ends"] == "2026-11-15T06:00:00-05:00"  # falls back to expires
    assert alerts[0]["instruction"] == ""


def test_metric(fake):
    with client_for(fake) as client:
        body = client.get("/weather", params={"units": "metric"}).json()

    assert body["units"] == {"temperature": "C", "speed": "km/h"}
    assert body["current"]["temperature"] == 5.0
    assert body["current"]["windSpeed"] == 16.1
    assert body["today"]["high"] == 10.0


def test_bad_units_rejected(fake):
    with client_for(fake) as client:
        assert client.get("/weather", params={"units": "kelvin"}).status_code == 422


def test_cached_between_requests(fake):
    with client_for(fake) as client:
        client.get("/weather")
        client.get("/weather", params={"units": "metric"})

    assert fake.calls == {"forecast": 1, "alerts": 1}


def test_old_data_served_when_refresh_fails(fake):
    settings = Settings(latitude=41.7225, longitude=-73.9343, forecast_ttl=0, alerts_ttl=0, retry_after=0)
    with client_for(fake, settings) as client:
        first = client.get("/weather").json()
        fake.failing = {"forecast", "alerts"}
        second = client.get("/weather")

    assert second.status_code == 200
    body = second.json()
    assert body["stale"] is True
    assert body["current"] == first["current"]
    assert body["updatedAt"] == first["updatedAt"]
    assert len(body["alerts"]) == 2


def test_failed_source_not_retried_immediately(fake):
    fake.failing = {"forecast"}
    with client_for(fake) as client:  # default retry_after is 30 s
        client.get("/weather")
        client.get("/weather")

    assert fake.calls["forecast"] == 1


def test_no_forecast_at_all_is_503(fake):
    fake.failing = {"forecast"}
    with client_for(fake) as client:
        response = client.get("/weather")

    assert response.status_code == 503
    assert response.json() == {"error": "Weather data is unavailable right now", "code": "weather_unavailable"}


def test_alerts_down_still_gives_weather(fake):
    fake.failing = {"alerts"}
    with client_for(fake) as client:
        body = client.get("/weather").json()

    assert body["alerts"] is None
    assert body["stale"] is True
    assert body["current"]["description"] == "Light rain"


def test_health(fake):
    with client_for(fake) as client:
        assert client.get("/health").json() == {"ok": True}
