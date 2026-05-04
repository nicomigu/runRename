from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.user import User
from app.routes.webhook import _process_activity


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


async def test_post_activity_create_accepted(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.auto_rename = True
    test_user.beta_user = True
    await db.commit()

    with patch("app.routes.webhook._spawn_task"):
        response = await client.post("/webhook", json={
            "object_type": "activity",
            "aspect_type": "create",
            "object_id": 999,
            "owner_id": test_user.strava_id,
        })
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

    result = await db.execute(
        select(Activity).where(Activity.strava_activity_id == 999)
    )
    placeholder = result.scalar_one()
    assert placeholder.generated_name == "pending"


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


async def test_post_subscribed_user_accepted(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.auto_rename = True
    test_user.beta_user = False
    test_user.subscribed = True
    await db.commit()

    with patch("app.routes.webhook._spawn_task"):
        response = await client.post("/webhook", json={
            "object_type": "activity",
            "aspect_type": "create",
            "object_id": 999,
            "owner_id": test_user.strava_id,
        })
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


async def test_post_duplicate_webhook_already_processed(
    client: AsyncClient, test_user: User, db: AsyncSession
):
    test_user.auto_rename = True
    test_user.beta_user = True
    await db.commit()

    db.add(Activity(
        user_id=test_user.id,
        strava_activity_id=999,
        generated_name="Already named",
    ))
    await db.commit()

    response = await client.post("/webhook", json={
        "object_type": "activity",
        "aspect_type": "create",
        "object_id": 999,
        "owner_id": test_user.strava_id,
    })
    assert response.status_code == 200
    assert response.json()["status"] == "already_processed"


async def test_process_activity_renames(
    test_user: User, db: AsyncSession, mock_http_client: AsyncClient,
):
    test_user.auto_rename = True
    test_user.beta_user = True
    await db.commit()

    db.add(Activity(
        user_id=test_user.id,
        strava_activity_id=12345,
        generated_name="pending",
        raw_context={"claimed": True},
    ))
    await db.commit()

    @asynccontextmanager
    async def fake_session():
        yield db

    with (
        patch("app.routes.webhook.PROCESSING_DELAY_SECONDS", 0),
        patch("app.routes.webhook.async_session", fake_session),
        patch(
            "app.services.claude.generate_name",
            new_callable=AsyncMock,
            return_value="the hill had other plans",
        ),
    ):
        await _process_activity(12345, test_user.id, mock_http_client)

    result = await db.execute(
        select(Activity).where(Activity.strava_activity_id == 12345)
    )
    activity = result.scalar_one()
    assert activity.generated_name == "the hill had other plans"
