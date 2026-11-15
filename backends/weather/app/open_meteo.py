# Current conditions, the next 12 hours and today's summary from Open-Meteo (no API key).
# Adapted from StormWatch's api/open_meteo.py. Docs: https://open-meteo.com/en/docs

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

URL = "https://api.open-meteo.com/v1/forecast"
HOURS_AHEAD = 12

# https://open-meteo.com/en/docs#weather_variable_documentation
WMO_CODES: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Light snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Moderate showers", 82: "Heavy showers",
    85: "Light snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


def describe(code: int) -> str:
    return WMO_CODES.get(code, "Unknown")


# everything below is metric (C, km/h)

@dataclass(frozen=True)
class Current:
    temperature: float
    feels_like: float
    humidity: float
    wind_speed: float
    wind_gusts: float
    wind_degrees: float
    weather_code: int
    is_day: bool


@dataclass(frozen=True)
class Hour:
    time: datetime
    temperature: float
    precipitation_chance: float
    weather_code: int
    is_day: bool


@dataclass(frozen=True)
class Today:
    high: float
    low: float
    precipitation_chance: float
    sunrise: datetime
    sunset: datetime


@dataclass(frozen=True)
class Forecast:
    timezone: str
    current: Current
    today: Today
    hourly: list[Hour]


async def fetch_forecast(client: httpx.AsyncClient, latitude: float, longitude: float) -> Forecast:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ",".join([
            "temperature_2m", "apparent_temperature", "relative_humidity_2m", "weather_code",
            "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "is_day",
        ]),
        "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        "forecast_hours": HOURS_AHEAD,
        "forecast_days": 1,
        "timezone": "auto",
    }
    response = await client.get(URL, params=params)
    response.raise_for_status()
    data = response.json()

    # times come back local with no offset
    zone = ZoneInfo(data["timezone"])

    def local_time(text: str) -> datetime:
        return datetime.fromisoformat(text).replace(tzinfo=zone)

    now, hourly, daily = data["current"], data["hourly"], data["daily"]
    return Forecast(
        timezone=data["timezone"],
        current=Current(
            temperature=now["temperature_2m"],
            feels_like=now["apparent_temperature"],
            humidity=now["relative_humidity_2m"],
            wind_speed=now["wind_speed_10m"],
            wind_gusts=now["wind_gusts_10m"],
            wind_degrees=now["wind_direction_10m"],
            weather_code=now["weather_code"],
            is_day=bool(now["is_day"]),
        ),
        today=Today(
            high=daily["temperature_2m_max"][0],
            low=daily["temperature_2m_min"][0],
            precipitation_chance=daily["precipitation_probability_max"][0] or 0,
            sunrise=local_time(daily["sunrise"][0]),
            sunset=local_time(daily["sunset"][0]),
        ),
        hourly=[
            Hour(
                time=local_time(time),
                temperature=hourly["temperature_2m"][i],
                precipitation_chance=hourly["precipitation_probability"][i] or 0,
                weather_code=hourly["weather_code"][i],
                is_day=bool(hourly["is_day"][i]),
            )
            for i, time in enumerate(hourly["time"])
        ],
    )
