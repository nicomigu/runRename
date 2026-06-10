import json
from unittest.mock import patch, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dependencies import create_session_cookie
from app.models.user import User

from tests.conftest import TestSession

settings = get_settings()


def _build_stripe_event(event_type: str, data: dict) -> dict:
    return {
        "type": event_type,
        "data": {"object": data},
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
    event = _build_stripe_event("checkout.session.completed", {
        "client_reference_id": str(test_user.id),
        "customer": "cus_abc123",
    })
    body = json.dumps(event).encode()

    with patch("stripe.Webhook.construct_event", return_value=event):
        resp = await client.post(
            "/payment/webhook",
            content=body,
            headers={"stripe-signature": "t=123,v1=fake", "content-type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    async with TestSession() as db:
        result = await db.execute(select(User).where(User.id == test_user.id))
        user = result.scalar_one()
        assert user.subscribed is True
        assert user.stripe_customer_id == "cus_abc123"


@pytest.mark.asyncio
async def test_webhook_subscription_deleted(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.subscribed = True
    test_user.stripe_customer_id = "cus_abc123"
    await db.commit()

    event = _build_stripe_event("customer.subscription.deleted", {
        "customer": "cus_abc123",
        "status": "canceled",
    })
    body = json.dumps(event).encode()

    with patch("stripe.Webhook.construct_event", return_value=event):
        resp = await client.post(
            "/payment/webhook",
            content=body,
            headers={"stripe-signature": "t=123,v1=fake", "content-type": "application/json"},
        )
    assert resp.status_code == 200

    async with TestSession() as db2:
        result = await db2.execute(select(User).where(User.id == test_user.id))
        user = result.scalar_one()
        assert user.subscribed is False


@pytest.mark.asyncio
async def test_webhook_subscription_updated_active(client: AsyncClient, test_user: User, db: AsyncSession):
    test_user.subscribed = False
    test_user.stripe_customer_id = "cus_abc123"
    await db.commit()

    event = _build_stripe_event("customer.subscription.updated", {
        "customer": "cus_abc123",
        "status": "active",
    })
    body = json.dumps(event).encode()

    with patch("stripe.Webhook.construct_event", return_value=event):
        resp = await client.post(
            "/payment/webhook",
            content=body,
            headers={"stripe-signature": "t=123,v1=fake", "content-type": "application/json"},
        )
    assert resp.status_code == 200

    async with TestSession() as db2:
        result = await db2.execute(select(User).where(User.id == test_user.id))
        user = result.scalar_one()
        assert user.subscribed is True


@pytest.mark.asyncio
async def test_webhook_invalid_signature(client: AsyncClient, test_user: User):
    event = _build_stripe_event("checkout.session.completed", {
        "client_reference_id": str(test_user.id),
        "customer": "cus_abc123",
    })
    body = json.dumps(event).encode()

    with patch("stripe.Webhook.construct_event", side_effect=__import__("stripe").SignatureVerificationError("bad", "sig")):
        resp = await client.post(
            "/payment/webhook",
            content=body,
            headers={"stripe-signature": "bad-signature", "content-type": "application/json"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_missing_signature(client: AsyncClient, test_user: User):
    event = _build_stripe_event("checkout.session.completed", {
        "client_reference_id": str(test_user.id),
        "customer": "cus_abc123",
    })
    body = json.dumps(event).encode()

    resp = await client.post(
        "/payment/webhook",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_unknown_user(client: AsyncClient):
    event = _build_stripe_event("checkout.session.completed", {
        "client_reference_id": "99999",
        "customer": "cus_abc123",
    })
    body = json.dumps(event).encode()

    with patch("stripe.Webhook.construct_event", return_value=event):
        resp = await client.post(
            "/payment/webhook",
            content=body,
            headers={"stripe-signature": "t=123,v1=fake", "content-type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "user_not_found"


@pytest.mark.asyncio
async def test_webhook_missing_client_reference_id(client: AsyncClient):
    event = _build_stripe_event("checkout.session.completed", {
        "customer": "cus_abc123",
    })
    body = json.dumps(event).encode()

    with patch("stripe.Webhook.construct_event", return_value=event):
        resp = await client.post(
            "/payment/webhook",
            content=body,
            headers={"stripe-signature": "t=123,v1=fake", "content-type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_webhook_ignored_event(client: AsyncClient, test_user: User):
    event = _build_stripe_event("invoice.paid", {
        "customer": "cus_abc123",
    })
    body = json.dumps(event).encode()

    with patch("stripe.Webhook.construct_event", return_value=event):
        resp = await client.post(
            "/payment/webhook",
            content=body,
            headers={"stripe-signature": "t=123,v1=fake", "content-type": "application/json"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_payment_success_page(client: AsyncClient, test_user: User):
    cookie = create_session_cookie(test_user.id)
    resp = await client.get("/payment/success", cookies={"session": cookie})
    assert resp.status_code == 200
    assert "You're in!" in resp.text
