from __future__ import annotations

import datetime
import json
import os
from typing import AsyncGenerator

import certifi
import httpx

from ..services.router import RouteDecision


DEFAULT_LAT, DEFAULT_LON = 50.7374, 7.0982


async def _fetch_weather(lat: float, lon: float, days: int = 3) -> str:
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
        "forecast_days": min(max(days, 1), 7),
        "timezone": "auto",
    }
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    async with httpx.AsyncClient(timeout=12, verify=certifi.where()) as client:
        response = await client.get(f"https://api.open-meteo.com/v1/forecast?{query_string}")
        response.raise_for_status()
        data = response.json()

    wmo = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Icy fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        80: "Slight showers",
        81: "Moderate showers",
        82: "Heavy showers",
        95: "Thunderstorm",
    }
    cur = data["current"]
    result = [
        f"Now: {wmo.get(cur['weather_code'], 'Unknown')}, {cur['temperature_2m']}°C, humidity {cur['relative_humidity_2m']}%, wind {cur['wind_speed_10m']} km/h",
        "",
        "Forecast:",
    ]
    for i, date in enumerate(data["daily"]["time"]):
        result.append(
            f"  {date}: {wmo.get(data['daily']['weather_code'][i], '?')}, "
            f"{data['daily']['temperature_2m_min'][i]}–{data['daily']['temperature_2m_max'][i]}°C, "
            f"rain {data['daily']['precipitation_sum'][i]}mm"
        )
    return "\n".join(result)


async def handle_weather(
    messages: list[dict],
    user_id: str,
    location: dict | None,
    attachments: list[str],
    decision: RouteDecision,
) -> AsyncGenerator[str, None]:
    """Handle weather queries."""
    lat = (location or {}).get("lat", DEFAULT_LAT)
    lon = (location or {}).get("lon", DEFAULT_LON)
    weather_text = await _fetch_weather(lat, lon, 3)
    yield weather_text
