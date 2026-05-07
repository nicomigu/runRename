import logging

import httpx

logger = logging.getLogger(__name__)

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

WMO_DESCRIPTIONS = {
    0: "clear sky",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "icy fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    80: "light showers", 81: "showers", 82: "heavy showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "heavy thunderstorm",
}


async def get_conditions(
    start_latlng: list[float] | None,
    client: httpx.AsyncClient,
) -> dict | None:
    if not start_latlng or len(start_latlng) < 2:
        logger.debug("Missing lat/lng, skipping weather")
        return None

    try:
        response = await client.get(
            WEATHER_URL,
            params={
                "latitude": start_latlng[0],
                "longitude": start_latlng[1],
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                "wind_speed_unit": "ms",
            },
        )
        response.raise_for_status()
        data = response.json()

        current = data.get("current", {})
        code = current.get("weather_code")

        return {
            "temp_c": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed_ms": current.get("wind_speed_10m"),
            "description": WMO_DESCRIPTIONS.get(code, "") if code is not None else "",
        }
    except Exception:
        logger.exception("Failed to fetch weather data")
        return None
