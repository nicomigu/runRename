import time

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.dependencies import create_session_cookie, get_http_client
from app.main import app
from app.models.user import User
from app.models.preference import Preference

engine = create_async_engine(
    "sqlite+aiosqlite://",
    echo=False,
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
TestSession = async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db():
    async with TestSession() as session:
        yield session


@pytest.fixture
def mock_strava_token_response() -> dict:
    return {
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
        "expires_at": int(time.time()) + 21600,
        "athlete": {
            "id": 12345,
            "firstname": "Nico",
            "lastname": "Runner",
            "profile": "https://example.com/pic.jpg",
        },
    }


EASY_RUN_ACTIVITY = {
    "id": 999,
    "name": "Morning Run",
    "type": "Run",
    "start_latlng": [-33.8, 151.2],
    "start_date": "2026-04-29T06:00:00Z",
    "distance": 10000,
    "moving_time": 3000,
    "average_heartrate": 145,
    "suffer_score": 50,
    "laps": [],
}

INTERVAL_ACTIVITY = {
    "id": 888,
    "name": "Afternoon Run",
    "type": "Run",
    "start_latlng": [-33.8, 151.2],
    "start_date": "2026-04-29T17:00:00Z",
    "distance": 12000,
    "moving_time": 3600,
    "laps": [
        {"distance": 2000, "elapsed_time": 600},
        {"distance": 1000, "elapsed_time": 240},
        {"distance": 200, "elapsed_time": 60},
        {"distance": 1000, "elapsed_time": 242},
        {"distance": 200, "elapsed_time": 58},
        {"distance": 1000, "elapsed_time": 238},
        {"distance": 200, "elapsed_time": 62},
        {"distance": 1500, "elapsed_time": 500},
    ],
}

WEATHER_RESPONSE = {
    "hourly": {
        "time": [
            "2026-04-29T00:00", "2026-04-29T01:00", "2026-04-29T02:00",
            "2026-04-29T03:00", "2026-04-29T04:00", "2026-04-29T05:00",
            "2026-04-29T06:00", "2026-04-29T07:00", "2026-04-29T08:00",
            "2026-04-29T09:00", "2026-04-29T10:00", "2026-04-29T11:00",
            "2026-04-29T12:00", "2026-04-29T13:00", "2026-04-29T14:00",
            "2026-04-29T15:00", "2026-04-29T16:00", "2026-04-29T17:00",
            "2026-04-29T18:00", "2026-04-29T19:00", "2026-04-29T20:00",
            "2026-04-29T21:00", "2026-04-29T22:00", "2026-04-29T23:00",
        ],
        "temperature_2m": [
            10.0, 9.5, 9.0, 9.2, 9.8, 12.0,
            14.0, 15.0, 16.0, 17.5, 19.0, 20.5,
            22.0, 23.0, 23.5, 23.0, 22.0, 20.0,
            18.5, 17.0, 15.5, 14.0, 13.0, 12.0,
        ],
        "relative_humidity_2m": [
            90, 91, 92, 92, 91, 88,
            82, 78, 72, 65, 58, 52,
            48, 45, 43, 45, 50, 55,
            62, 68, 75, 80, 84, 87,
        ],
        "wind_speed_10m": [
            1.5, 1.2, 1.0, 1.3, 1.8, 2.5,
            3.1, 3.5, 4.0, 4.2, 4.5, 4.3,
            4.0, 3.8, 3.5, 3.2, 3.0, 2.8,
            2.5, 2.2, 2.0, 1.8, 1.5, 1.3,
        ],
        "weather_code": [
            3, 3, 3, 3, 3, 45,
            63, 61, 2, 1, 0, 0,
            0, 0, 1, 2, 3, 61,
            63, 3, 3, 3, 3, 3,
        ],
    }
}


@pytest.fixture
async def mock_http_client(mock_strava_token_response: dict) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: _mock_handler(request, mock_strava_token_response)
    ))
    yield client
    await client.aclose()


def _mock_handler(request: httpx.Request, token_response: dict) -> httpx.Response:
    url = str(request.url)
    if "strava.com/oauth/token" in url:
        return httpx.Response(200, json=token_response)
    if "strava.com/api/v3/activities/888" in url:
        if request.method == "GET":
            return httpx.Response(200, json=INTERVAL_ACTIVITY)
        if request.method == "PUT":
            return httpx.Response(200, json={"id": 888, "name": "Updated"})
    if "strava.com/api/v3/activities/12345" in url:
        if request.method == "GET":
            return httpx.Response(200, json={**EASY_RUN_ACTIVITY, "id": 12345})
        if request.method == "PUT":
            return httpx.Response(200, json={"id": 12345, "name": "Updated"})
    if "strava.com/api/v3/activities/999" in url:
        if request.method == "GET":
            return httpx.Response(200, json=EASY_RUN_ACTIVITY)
        if request.method == "PUT":
            return httpx.Response(200, json={"id": 999, "name": "Updated"})
    if "open-meteo.com" in url:
        if "current=" in url:
            return httpx.Response(200, json={
                "current": {
                    "temperature_2m": 16.0,
                    "relative_humidity_2m": 72,
                    "wind_speed_10m": 4.0,
                    "weather_code": 2,
                }
            })
        return httpx.Response(200, json=WEATHER_RESPONSE)
    return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
async def test_user(db: AsyncSession) -> User:
    user = User(
        strava_id=12345,
        access_token="test_access",
        refresh_token="test_refresh",
        expires_at=int(time.time()) + 3600,
        name="Nico Runner",
    )
    db.add(user)
    await db.flush()
    db.add(Preference(user_id=user.id))
    await db.commit()
    await db.refresh(user)
    return user


@pytest.fixture
async def expired_user(db: AsyncSession) -> User:
    user = User(
        strava_id=99999,
        access_token="old_access",
        refresh_token="old_refresh",
        expires_at=int(time.time()) - 3600,
        name="Expired User",
    )
    db.add(user)
    await db.flush()
    db.add(Preference(user_id=user.id))
    await db.commit()
    await db.refresh(user)
    return user


async def _override_get_db():
    async with TestSession() as session:
        yield session


@pytest.fixture
async def client(mock_http_client: httpx.AsyncClient):
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_http_client] = lambda: mock_http_client
    app.state.http_client = mock_http_client
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
