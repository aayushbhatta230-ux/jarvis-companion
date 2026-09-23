"""Live Weather Tool for JARVIS backed by Open-Meteo API.

Completely free, open-access, zero-key weather service providing global
temperature, weather conditions, wind speed, and forecasts.
"""

from __future__ import annotations

import requests

WMO_WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    61: "slight rain",
    62: "moderate rain",
    63: "heavy rain",
    71: "slight snowfall",
    73: "moderate snowfall",
    75: "heavy snowfall",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def get_weather(location: str = "") -> str:
    """Fetch current live weather for a city or location.

    Parameters
    ----------
    location: str
        Name of city/region (defaults to London or user's location if blank).
    """
    city = (location or "").strip()
    if not city or city.lower() in ("here", "current location", "my location", "outside", "today"):
        city = "Kathmandu"  # Default fallback if location not specified

    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(city)}&count=1"
        geo_res = requests.get(geo_url, timeout=4).json()
        results = geo_res.get("results")
        if not results:
            return f"I couldn't find location data for '{city}'."

        loc = results[0]
        name = loc.get("name", city)
        country = loc.get("country", "")
        lat = loc["latitude"]
        lon = loc["longitude"]

        forecast_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current_weather=true"
        )
        weather_res = requests.get(forecast_url, timeout=4).json()
        current = weather_res.get("current_weather", {})
        temp = current.get("temperature")
        code = current.get("weathercode", 0)
        wind = current.get("windspeed", 0)
        condition = WMO_WEATHER_CODES.get(code, "fair")

        loc_label = f"{name}, {country}" if country else name
        return f"Currently in {loc_label}: {temp}°C, {condition}, with winds at {wind} km/h."
    except Exception as exc:
        return f"Unable to retrieve weather right now: {exc}"
