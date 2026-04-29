import time

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User

settings = get_settings()

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"


async def refresh_token_if_expired(
    user: User, db: AsyncSession, client: httpx.AsyncClient
) -> None:
    if user.expires_at > time.time():
        return
    response = await client.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": settings.STRAVA_CLIENT_ID,
            "client_secret": settings.STRAVA_CLIENT_SECRET,
            "refresh_token": user.refresh_token,
            "grant_type": "refresh_token",
        },
    )
    response.raise_for_status()
    token_data = response.json()
    user.access_token = token_data["access_token"]
    user.refresh_token = token_data["refresh_token"]
    user.expires_at = token_data["expires_at"]
    await db.commit()


async def get_activity(
    activity_id: int, user: User, db: AsyncSession, client: httpx.AsyncClient
) -> dict:
    await refresh_token_if_expired(user, db, client)
    response = await client.get(
        f"{STRAVA_API_BASE}/activities/{activity_id}",
        headers={"Authorization": f"Bearer {user.access_token}"},
    )
    response.raise_for_status()
    return response.json()


async def patch_activity_name(
    activity_id: int, name: str, user: User, db: AsyncSession, client: httpx.AsyncClient
) -> None:
    await refresh_token_if_expired(user, db, client)
    response = await client.put(
        f"{STRAVA_API_BASE}/activities/{activity_id}",
        headers={"Authorization": f"Bearer {user.access_token}"},
        json={"name": name},
    )
    response.raise_for_status()
