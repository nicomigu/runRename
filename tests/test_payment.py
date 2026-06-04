import hashlib
import hmac
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.dependencies import create_session_cookie, get_http_client
from app.main import app
from app.models.user import User

from tests.conftest import TestSession, _override_get_db

settings = get_settings()

WEBHOOK_SECRET = settings.LEMON_SQUEEZY_WEBHOOK_SECRET


def _sign(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _subscription_event(event_name: str, user_id: int, customer_id: str = "12345", status: str = "active") -> dict:
    return {
        "meta": {
            "event_name": event_name,
            "custom_data": {"user_id": str(user_id)},
        },
        "data": {
            "attributes": {
                "customer_id": customer_id,
                "status": status,
            }
        },
    }


@pytest.mark.asyncio
async def test_checkout_redirects_when_already_subscribed(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.subscribed = True
    await db.commit()

    cookie = create_session_cookie(test_user.id)
    resp = await client.get("/payment/checkout", cookies={"session": cookie}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"


@pytest.mark.asyncio
async def test_checkout_redirects_when_beta_user(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.beta_user = True
    await db.commit()

    cookie = create_session_cookie(test_user.id)
    resp = await client.get("/payment/checkout", cookies={"session": cookie}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"


@pytest.mark.asyncio
async def test_checkout_requires_auth(client: AsyncClient):
    resp = await client.get("/payment/checkout", follow_redirects=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_subscription_created(client: AsyncClient, test_user: User):
    payload = _subscription_event("subscription_created", test_user.id)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"x-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    async with TestSession() as db:
        result = await db.execute(select(User).where(User.id == test_user.id))
        user = result.scalar_one()
        assert user.subscribed is True
        assert user.lemon_squeezy_customer_id == "12345"


@pytest.mark.asyncio
async def test_webhook_subscription_updated_cancelled(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.subscribed = True
    test_user.lemon_squeezy_customer_id = "12345"
    await db.commit()

    payload = _subscription_event("subscription_updated", test_user.id, status="cancelled")
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"x-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200

    async with TestSession() as db2:
        result = await db2.execute(select(User).where(User.id == test_user.id))
        user = result.scalar_one()
        assert user.subscribed is False


@pytest.mark.asyncio
async def test_webhook_subscription_cancelled(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.subscribed = True
    test_user.lemon_squeezy_customer_id = "12345"
    await db.commit()

    payload = _subscription_event("subscription_cancelled", test_user.id)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"x-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200

    async with TestSession() as db2:
        result = await db2.execute(select(User).where(User.id == test_user.id))
        user = result.scalar_one()
        assert user.subscribed is False


@pytest.mark.asyncio
async def test_webhook_subscription_expired(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.subscribed = True
    test_user.lemon_squeezy_customer_id = "12345"
    await db.commit()

    payload = _subscription_event("subscription_expired", test_user.id)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"x-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200

    async with TestSession() as db2:
        result = await db2.execute(select(User).where(User.id == test_user.id))
        user = result.scalar_one()
        assert user.subscribed is False


@pytest.mark.asyncio
async def test_webhook_subscription_resumed(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.subscribed = False
    test_user.lemon_squeezy_customer_id = "12345"
    await db.commit()

    payload = _subscription_event("subscription_resumed", test_user.id)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"x-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200

    async with TestSession() as db2:
        result = await db2.execute(select(User).where(User.id == test_user.id))
        user = result.scalar_one()
        assert user.subscribed is True


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client: AsyncClient, test_user: User):
    payload = _subscription_event("subscription_created", test_user.id)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"x-signature": "bad-signature", "content-type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_missing_signature(client: AsyncClient, test_user: User):
    payload = _subscription_event("subscription_created", test_user.id)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_unknown_user(client: AsyncClient):
    payload = _subscription_event("subscription_created", 99999)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"x-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "user_not_found"


@pytest.mark.asyncio
async def test_webhook_missing_user_id(client: AsyncClient):
    payload = {
        "meta": {"event_name": "subscription_created", "custom_data": {}},
        "data": {"attributes": {"customer_id": "12345", "status": "active"}},
    }
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"x-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_webhook_ignored_event(client: AsyncClient, test_user: User):
    payload = _subscription_event("order_created", test_user.id)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"x-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_payment_success_page(client: AsyncClient, test_user: User):
    cookie = create_session_cookie(test_user.id)
    resp = await client.get("/payment/success", cookies={"session": cookie})
    assert resp.status_code == 200
    assert "You're in!" in resp.text
