import time

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.strava import get_activity, patch_activity_name, refresh_token_if_expired


async def test_refresh_skips_when_fresh(
    test_user: User, db: AsyncSession, mock_http_client: httpx.AsyncClient
):
    original_token = test_user.access_token
    await refresh_token_if_expired(test_user, db, mock_http_client)
    assert test_user.access_token == original_token


async def test_refresh_updates_when_expired(
    expired_user: User, db: AsyncSession, mock_http_client: httpx.AsyncClient
):
    assert expired_user.expires_at < time.time()
    await refresh_token_if_expired(expired_user, db, mock_http_client)
    assert expired_user.access_token == "new_access_token"
    assert expired_user.refresh_token == "new_refresh_token"
    assert expired_user.expires_at > time.time()


async def test_get_activity(
    test_user: User, db: AsyncSession, mock_http_client: httpx.AsyncClient
):
    activity = await get_activity(999, test_user, db, mock_http_client)
    assert activity["id"] == 999
    assert activity["name"] == "Morning Run"


async def test_patch_activity_name(
    test_user: User, db: AsyncSession, mock_http_client: httpx.AsyncClient
):
    await patch_activity_name(999, "New Name", test_user, db, mock_http_client)
