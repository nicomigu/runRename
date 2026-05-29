import httpx

from app.services.weather import get_conditions


async def test_get_conditions_with_start_date(mock_http_client: httpx.AsyncClient):
    result = await get_conditions(
        [-33.8, 151.2], mock_http_client,
        start_date="2026-04-29T06:00:00Z", elapsed_time=3000,
    )
    assert result is not None
    assert result["temp_c"] == 14.0
    assert result["humidity"] == 82
    assert result["wind_speed_ms"] == 3.1
    assert result["description"] == "rain"


async def test_get_conditions_multi_hour(mock_http_client: httpx.AsyncClient):
    result = await get_conditions(
        [-33.8, 151.2], mock_http_client,
        start_date="2026-04-29T17:00:00Z", elapsed_time=3600,
    )
    assert result is not None
    assert result["temp_c"] == 19.2
    assert result["humidity"] == 58
    assert result["wind_speed_ms"] == 2.6
    assert result["description"] == "rain"


async def test_get_conditions_no_start_date_falls_back_to_current(mock_http_client: httpx.AsyncClient):
    result = await get_conditions([-33.8, 151.2], mock_http_client)
    assert result is not None
    assert result["temp_c"] == 16.0
    assert result["humidity"] == 72
    assert result["wind_speed_ms"] == 4.0
    assert result["description"] == "partly cloudy"


async def test_get_conditions_invalid_start_date_falls_back_to_current(mock_http_client: httpx.AsyncClient):
    result = await get_conditions(
        [-33.8, 151.2], mock_http_client,
        start_date="not-a-date", elapsed_time=3000,
    )
    assert result is not None
    assert result["temp_c"] == 16.0


async def test_get_conditions_no_latlng(mock_http_client: httpx.AsyncClient):
    result = await get_conditions(None, mock_http_client)
    assert result is None


async def test_get_conditions_empty_latlng(mock_http_client: httpx.AsyncClient):
    result = await get_conditions([], mock_http_client)
    assert result is None
