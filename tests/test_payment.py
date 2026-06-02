import hashlib
import hmac
import json
import time

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

WEBHOOK_SECRET = settings.STRIPE_WEBHOOK_SECRET


def _sign(body: bytes, timestamp: int | None = None) -> str:
    ts = timestamp or int(time.time())
    signed_payload = f"{ts}.{body.decode()}"
    sig = hmac.new(WEBHOOK_SECRET.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _checkout_event(user_id: int, customer_id: str = "cus_test123") -> dict:
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": str(user_id),
                "metadata": {"user_id": str(user_id)},
                "customer": customer_id,
            }
        },
    }


def _subscription_event(event_type: str, customer_id: str, status: str = "active") -> dict:
    return {
        "type": event_type,
        "data": {
            "object": {
                "customer": customer_id,
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
async def test_webhook_checkout_completed(client: AsyncClient, test_user: User):
    payload = _checkout_event(test_user.id)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"stripe-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    async with TestSession() as db:
        result = await db.execute(select(User).where(User.id == test_user.id))
        user = result.scalar_one()
        assert user.subscribed is True
        assert user.stripe_customer_id == "cus_test123"


@pytest.mark.asyncio
async def test_webhook_subscription_updated_cancelled(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.subscribed = True
    test_user.stripe_customer_id = "cus_cancel"
    await db.commit()

    payload = _subscription_event("customer.subscription.updated", "cus_cancel", status="canceled")
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"stripe-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200

    async with TestSession() as db2:
        result = await db2.execute(select(User).where(User.id == test_user.id))
        user = result.scalar_one()
        assert user.subscribed is False


@pytest.mark.asyncio
async def test_webhook_subscription_deleted(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.subscribed = True
    test_user.stripe_customer_id = "cus_delete"
    await db.commit()

    payload = _subscription_event("customer.subscription.deleted", "cus_delete")
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"stripe-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200

    async with TestSession() as db2:
        result = await db2.execute(select(User).where(User.id == test_user.id))
        user = result.scalar_one()
        assert user.subscribed is False


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client: AsyncClient, test_user: User):
    payload = _checkout_event(test_user.id)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"stripe-signature": "t=123,v1=bad", "content-type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_missing_signature(client: AsyncClient, test_user: User):
    payload = _checkout_event(test_user.id)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_expired_signature(client: AsyncClient, test_user: User):
    payload = _checkout_event(test_user.id)
    body = json.dumps(payload).encode()
    old_timestamp = int(time.time()) - 600

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"stripe-signature": _sign(body, old_timestamp), "content-type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_unknown_user(client: AsyncClient):
    payload = _checkout_event(99999)
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"stripe-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "user_not_found"


@pytest.mark.asyncio
async def test_webhook_ignored_event(client: AsyncClient):
    payload = {"type": "payment_intent.succeeded", "data": {"object": {}}}
    body = json.dumps(payload).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"stripe-signature": _sign(body), "content-type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_payment_success_page(client: AsyncClient, test_user: User):
    cookie = create_session_cookie(test_user.id)
    resp = await client.get("/payment/success", cookies={"session": cookie})
    assert resp.status_code == 200
    assert "You're in!" in resp.text
