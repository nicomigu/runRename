import httpx

from app.services.weather import get_conditions
from tests.conftest import WEATHER_RESPONSE


async def test_get_conditions_success(mock_http_client: httpx.AsyncClient):
    result = await get_conditions([-33.8, 151.2], "2026-04-29T06:00:00Z", mock_http_client)
    assert result is not None
    assert result["temp_c"] == 14.5
    assert result["humidity"] == 82
    assert result["description"] == "light rain"


async def test_get_conditions_no_latlng(mock_http_client: httpx.AsyncClient):
    result = await get_conditions(None, "2026-04-29T06:00:00Z", mock_http_client)
    assert result is None


async def test_get_conditions_empty_latlng(mock_http_client: httpx.AsyncClient):
    result = await get_conditions([], "2026-04-29T06:00:00Z", mock_http_client)
    assert result is None


async def test_get_conditions_no_date(mock_http_client: httpx.AsyncClient):
    result = await get_conditions([-33.8, 151.2], None, mock_http_client)
    assert result is None
