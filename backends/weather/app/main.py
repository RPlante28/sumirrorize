"""
Weather for the mirror's location. Run with:
    uvicorn --factory app.main:create_app --port 3200
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import nws, open_meteo, units
from .cache import Cached, Unavailable
from .config import Settings, load_settings
from .models import Alert, Current, Error, Hour, Location, Today, UnitLabels, Weather
from .units import Units

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# The NWS asks every client to identify itself.
USER_AGENT = "Sumirrorize/1.0 (smart mirror weather service)"


class WeatherSource:
    """Fetches and caches the forecast and alerts for one location."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        lat, lon = settings.latitude, settings.longitude
        self.forecast = Cached(
            "forecast", lambda: open_meteo.fetch_forecast(client, lat, lon),
            settings.forecast_ttl, settings.retry_after,
        )
        self.alerts = Cached(
            "alerts", lambda: nws.fetch_alerts(client, lat, lon),
            settings.alerts_ttl, settings.retry_after,
        )


def to_response(settings: Settings, forecast, alerts, unit: Units) -> Weather:
    f: open_meteo.Forecast = forecast.value
    temp = lambda c: units.temperature(c, unit)  # noqa: E731
    speed = lambda k: units.speed(k, unit)  # noqa: E731
    return Weather(
        location=Location(
            label=settings.label, latitude=settings.latitude,
            longitude=settings.longitude, timezone=f.timezone,
        ),
        units=UnitLabels(**units.LABELS[unit]),
        current=Current(
            temperature=temp(f.current.temperature),
            feels_like=temp(f.current.feels_like),
            humidity=f.current.humidity,
            wind_speed=speed(f.current.wind_speed),
            wind_gusts=speed(f.current.wind_gusts),
            wind_direction=units.compass(f.current.wind_degrees),
            description=open_meteo.describe(f.current.weather_code),
            weather_code=f.current.weather_code,
            is_day=f.current.is_day,
        ),
        today=Today(
            high=temp(f.today.high), low=temp(f.today.low),
            precipitation_chance=f.today.precipitation_chance,
            sunrise=f.today.sunrise, sunset=f.today.sunset,
        ),
        hourly=[
            Hour(
                time=h.time, temperature=temp(h.temperature),
                precipitation_chance=h.precipitation_chance,
                description=open_meteo.describe(h.weather_code),
                weather_code=h.weather_code, is_day=h.is_day,
            )
            for h in f.hourly
        ],
        alerts=None if alerts is None else [Alert(**vars(a)) for a in alerts.value],
        updated_at=forecast.fetched_at,
        stale=forecast.stale or alerts is None or alerts.stale,
    )


def create_app(settings: Optional[Settings] = None, transport: Optional[httpx.AsyncBaseTransport] = None) -> FastAPI:
    """`transport` lets tests swap in fake weather APIs."""
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(
            transport=transport, timeout=15, headers={"User-Agent": USER_AGENT}
        ) as client:
            app.state.source = WeatherSource(settings, client)
            yield

    app = FastAPI(title="Sumirrorize weather", lifespan=lifespan)

    @app.get("/weather", response_model=Weather, responses={503: {"model": Error}})
    async def weather(request: Request, units: Units = Units.imperial):
        """Current conditions, today's high/low, the next 12 hours, and active alerts."""
        source: WeatherSource = request.app.state.source
        forecast, alerts = await asyncio.gather(
            source.forecast.get(), source.alerts.get(), return_exceptions=True
        )
        if isinstance(forecast, BaseException):
            if not isinstance(forecast, Unavailable):
                raise forecast
            return JSONResponse(
                status_code=503,
                content={"error": "Weather data is unavailable right now", "code": "weather_unavailable"},
            )
        if isinstance(alerts, BaseException):
            if not isinstance(alerts, Unavailable):
                raise alerts
            alerts = None
        return to_response(settings, forecast, alerts, units)

    @app.get("/health")
    async def health():
        return {"ok": True}

    return app
