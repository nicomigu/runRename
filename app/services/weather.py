import logging
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_FIELDS = "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"

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

WMO_SEVERITY = {code: i for i, code in enumerate(sorted(WMO_DESCRIPTIONS.keys()))}


def _parse_activity_time(start_date: str) -> datetime:
    return datetime.fromisoformat(start_date.replace("Z", "+00:00")).astimezone(timezone.utc)


def _hours_spanned(start: datetime, elapsed_seconds: int) -> list[str]:
    end = start + timedelta(seconds=elapsed_seconds)
    hours: list[str] = []
    current = start.replace(minute=0, second=0, microsecond=0)
    while current <= end:
        hours.append(current.strftime("%Y-%m-%dT%H:00"))
        current += timedelta(hours=1)
    return hours


def _extract_hourly_values(hourly: dict, target_hours: list[str], field: str) -> list:
    times = hourly.get("time", [])
    values = hourly.get(field, [])
    target_set = set(target_hours)
    results = []
    for i, t in enumerate(times):
        if t in target_set and i < len(values) and values[i] is not None:
            results.append(values[i])
    return results


def _aggregate_hourly(hourly: dict, target_hours: list[str]) -> dict | None:
    temps = _extract_hourly_values(hourly, target_hours, "temperature_2m")
    humidities = _extract_hourly_values(hourly, target_hours, "relative_humidity_2m")
    winds = _extract_hourly_values(hourly, target_hours, "wind_speed_10m")
    codes = _extract_hourly_values(hourly, target_hours, "weather_code")

    if not temps:
        return None

    worst_code = max(codes, key=lambda c: WMO_SEVERITY.get(int(c), 0)) if codes else None

    return {
        "temp_c": round(sum(temps) / len(temps), 1),
        "humidity": round(sum(humidities) / len(humidities)) if humidities else None,
        "wind_speed_ms": round(sum(winds) / len(winds), 1) if winds else None,
        "description": WMO_DESCRIPTIONS.get(int(worst_code), "") if worst_code is not None else "",
    }


async def get_conditions(
    start_latlng: list[float] | None,
    client: httpx.AsyncClient,
    start_date: str | None = None,
    elapsed_time: int | None = None,
) -> dict | None:
    if not start_latlng or len(start_latlng) < 2:
        logger.debug("Missing lat/lng, skipping weather")
        return None

    lat, lon = start_latlng[0], start_latlng[1]

    if not start_date:
        return await _get_current(lat, lon, client)

    try:
        activity_start = _parse_activity_time(start_date)
    except ValueError:
        logger.warning("Could not parse start_date %r, falling back to current weather", start_date)
        return await _get_current(lat, lon, client)

    target_hours = _hours_spanned(activity_start, elapsed_time or 3600)
    start_date_str = target_hours[0][:10]
    end_date_str = target_hours[-1][:10]

    now_utc = datetime.now(timezone.utc)
    if activity_start > now_utc - timedelta(days=5):
        url = FORECAST_URL
    else:
        url = ARCHIVE_URL

    return await _get_hourly(lat, lon, start_date_str, end_date_str, target_hours, url, client)


async def _get_hourly(
    lat: float, lon: float, start_date: str, end_date: str,
    target_hours: list[str], url: str, client: httpx.AsyncClient,
) -> dict | None:
    try:
        response = await client.get(
            url,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": end_date,
                "hourly": HOURLY_FIELDS,
                "wind_speed_unit": "ms",
            },
        )
        response.raise_for_status()
        data = response.json()
        return _aggregate_hourly(data.get("hourly", {}), target_hours)
    except Exception:
        logger.exception("Failed to fetch hourly weather data")
        return None


async def _get_current(
    lat: float, lon: float, client: httpx.AsyncClient,
) -> dict | None:
    try:
        response = await client.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
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
