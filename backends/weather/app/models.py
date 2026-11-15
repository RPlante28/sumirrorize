# the JSON we return. camelCase keys, same as d3l

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Location(Model):
    label: str
    latitude: float
    longitude: float
    timezone: str


class UnitLabels(Model):
    temperature: str  # "F" or "C"
    speed: str        # "mph" or "km/h"


class Current(Model):
    temperature: float
    feels_like: float
    humidity: float               # percent
    wind_speed: float
    wind_gusts: float
    wind_direction: str           # compass point, e.g. "NW"
    description: str              # e.g. "Partly cloudy"
    weather_code: int  # WMO code
    is_day: bool


class Today(Model):
    high: float
    low: float
    precipitation_chance: float   # percent, the day's highest
    sunrise: datetime
    sunset: datetime


class Hour(Model):
    time: datetime
    temperature: float
    precipitation_chance: float   # percent
    description: str
    weather_code: int
    is_day: bool


class Alert(Model):
    event: str
    headline: str
    severity: str
    urgency: str
    area: str
    starts: Optional[datetime]
    ends: Optional[datetime]
    description: str
    instruction: str


class Weather(Model):
    location: Location
    units: UnitLabels
    current: Current
    today: Today
    hourly: list[Hour]
    # None = couldn't fetch alerts, [] = none right now
    alerts: Optional[list[Alert]]
    updated_at: datetime          # when the forecast was fetched
    # some of this is old because the last fetch failed
    stale: bool


class Error(Model):
    error: str
    code: str
