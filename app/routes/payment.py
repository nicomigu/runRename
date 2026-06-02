import hashlib
import hmac
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.dependencies import get_current_user, get_http_client
from app.models.user import User

import httpx

router = APIRouter(prefix="/payment", tags=["payment"])
settings = get_settings()
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

STRIPE_API = "https://api.stripe.com/v1"
SIGNATURE_TOLERANCE = 300


@router.get("/checkout")
async def checkout(
    user: User = Depends(get_current_user),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    if user.beta_user or user.subscribed:
        return RedirectResponse(url="/dashboard", status_code=302)

    if not settings.STRIPE_PRICE_ID:
        raise HTTPException(status_code=503, detail="Payments not configured")

    form_data = {
        "mode": "subscription",
        "line_items[0][price]": settings.STRIPE_PRICE_ID,
        "line_items[0][quantity]": "1",
        "success_url": f"{settings.BASE_URL}/payment/success",
        "cancel_url": f"{settings.BASE_URL}/dashboard",
        "client_reference_id": str(user.id),
        "metadata[user_id]": str(user.id),
    }

    resp = await client.post(
        f"{STRIPE_API}/checkout/sessions",
        content=urlencode(form_data),
        headers={
            "Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    if resp.status_code != 200:
        logger.error("Stripe checkout failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail="Failed to create checkout session")

    checkout_url = resp.json()["url"]
    return RedirectResponse(url=checkout_url, status_code=303)


def _verify_stripe_signature(body: bytes, sig_header: str) -> None:
    parts = dict(pair.split("=", 1) for pair in sig_header.split(","))
    timestamp = parts.get("t", "")
    signature = parts.get("v1", "")

    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Invalid signature header")

    if abs(time.time() - int(timestamp)) > SIGNATURE_TOLERANCE:
        raise HTTPException(status_code=401, detail="Signature timestamp expired")

    signed_payload = f"{timestamp}.{body.decode()}"
    expected = hmac.new(
        settings.STRIPE_WEBHOOK_SECRET.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    sig_header = request.headers.get("stripe-signature")
    if not sig_header:
        raise HTTPException(status_code=401, detail="Missing signature")

    body = await request.body()
    _verify_stripe_signature(body, sig_header)

    event = json.loads(body)
    event_type = event.get("type")
    obj = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("user_id")
        customer_id = obj.get("customer")

        if not user_id:
            logger.warning("Stripe checkout.session.completed missing user_id")
            return {"status": "ignored"}

        result = await db.execute(select(User).where(User.id == int(user_id)))
        user = result.scalar_one_or_none()
        if user is None:
            logger.warning("Stripe webhook for unknown user_id=%s", user_id)
            return {"status": "user_not_found"}

        user.subscribed = True
        if customer_id:
            user.stripe_customer_id = customer_id
        await db.commit()
        logger.info("User %s subscribed via Stripe", user_id)
        return {"status": "ok"}

    if event_type == "customer.subscription.updated":
        status = obj.get("status")
        customer_id = obj.get("customer")

        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            logger.warning("Stripe subscription update for unknown customer=%s", customer_id)
            return {"status": "customer_not_found"}

        user.subscribed = status in ("active", "trialing")
        await db.commit()
        logger.info("User %s subscription updated: status=%s", user.id, status)
        return {"status": "ok"}

    if event_type == "customer.subscription.deleted":
        customer_id = obj.get("customer")

        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            logger.warning("Stripe subscription deleted for unknown customer=%s", customer_id)
            return {"status": "customer_not_found"}

        user.subscribed = False
        await db.commit()
        logger.info("User %s subscription cancelled", user.id)
        return {"status": "ok"}

    return {"status": "ignored"}


@router.get("/success", response_class=HTMLResponse)
async def payment_success(
    request: Request,
    user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "payment_success.html", context={
        "user": user,
    })
