import logging

import httpx

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"


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
                "lat": start_latlng[0],
                "lon": start_latlng[1],
                "appid": settings.OPENWEATHERMAP_KEY,
                "units": "metric",
            },
        )
        response.raise_for_status()
        data = response.json()

        main = data.get("main", {})
        wind = data.get("wind", {})
        weather_list = data.get("weather") or []
        weather_desc = weather_list[0].get("description", "") if weather_list else ""

        return {
            "temp_c": main.get("temp"),
            "humidity": main.get("humidity"),
            "wind_speed_ms": wind.get("speed"),
            "description": weather_desc,
        }
    except Exception:
        logger.exception("Failed to fetch weather data")
        return None
