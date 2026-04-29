from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def test_verify_webhook_valid_token(client: AsyncClient):
    response = await client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "abc123",
            "hub.verify_token": "test",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"hub.challenge": "abc123"}


async def test_verify_webhook_invalid_token(client: AsyncClient):
    response = await client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "abc123",
            "hub.verify_token": "wrong_token",
        },
    )
    assert response.status_code == 403


async def test_post_activity_create_processed(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.auto_rename = True
    test_user.beta_user = True
    await db.commit()

    with patch(
        "app.services.claude.generate_name",
        new_callable=AsyncMock,
        return_value="Rainy dawn miles before work",
    ):
        response = await client.post("/webhook", json={
            "object_type": "activity",
            "aspect_type": "create",
            "object_id": 999,
            "owner_id": test_user.strava_id,
        })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["new_name"] == "Rainy dawn miles before work"


async def test_post_non_activity_ignored(client: AsyncClient):
    response = await client.post("/webhook", json={
        "object_type": "athlete",
        "aspect_type": "update",
        "object_id": 123,
        "owner_id": 99999,
    })
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


async def test_post_activity_update_ignored(client: AsyncClient):
    response = await client.post("/webhook", json={
        "object_type": "activity",
        "aspect_type": "update",
        "object_id": 123,
        "owner_id": 99999,
    })
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


async def test_post_unknown_user(client: AsyncClient):
    response = await client.post("/webhook", json={
        "object_type": "activity",
        "aspect_type": "create",
        "object_id": 123,
        "owner_id": 77777,
    })
    assert response.status_code == 200
    assert response.json()["status"] == "user_not_found"


async def test_post_auto_rename_disabled(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.auto_rename = False
    test_user.beta_user = True
    await db.commit()

    response = await client.post("/webhook", json={
        "object_type": "activity",
        "aspect_type": "create",
        "object_id": 999,
        "owner_id": test_user.strava_id,
    })
    assert response.status_code == 200
    assert response.json()["status"] == "auto_rename_disabled"


async def test_post_not_authorized(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.auto_rename = True
    test_user.beta_user = False
    test_user.subscribed = False
    await db.commit()

    response = await client.post("/webhook", json={
        "object_type": "activity",
        "aspect_type": "create",
        "object_id": 999,
        "owner_id": test_user.strava_id,
    })
    assert response.status_code == 200
    assert response.json()["status"] == "not_authorized"
