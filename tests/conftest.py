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
    "current": {
        "temperature_2m": 14.5,
        "relative_humidity_2m": 82,
        "wind_speed_10m": 3.1,
        "weather_code": 63,
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
