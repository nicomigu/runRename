import logging
from datetime import datetime

import httpx

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

ONECALL_URL = "https://api.openweathermap.org/data/3.0/onecall/timemachine"


async def get_conditions(
    start_latlng: list[float] | None,
    start_date: str | None,
    client: httpx.AsyncClient,
) -> dict | None:
    if not start_latlng or len(start_latlng) < 2 or not start_date:
        logger.debug("Missing lat/lng or start_date, skipping weather")
        return None

    try:
        dt = int(datetime.fromisoformat(start_date.replace("Z", "+00:00")).timestamp())
        response = await client.get(
            ONECALL_URL,
            params={
                "lat": start_latlng[0],
                "lon": start_latlng[1],
                "dt": dt,
                "appid": settings.OPENWEATHERMAP_KEY,
                "units": "metric",
            },
        )
        response.raise_for_status()
        data = response.json()

        current = data.get("data", [{}])[0]
        weather_desc = current.get("weather", [{}])[0].get("description", "")

        return {
            "temp_c": current.get("temp"),
            "humidity": current.get("humidity"),
            "wind_speed_ms": current.get("wind_speed"),
            "description": weather_desc,
        }
    except Exception:
        logger.exception("Failed to fetch weather data")
        return None
