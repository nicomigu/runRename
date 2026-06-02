import hashlib
import hmac
import json
import logging
from pathlib import Path

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

LEMONSQUEEZY_API = "https://api.lemonsqueezy.com/v1"


@router.get("/checkout")
async def checkout(
    user: User = Depends(get_current_user),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    if user.beta_user or user.subscribed:
        return RedirectResponse(url="/dashboard", status_code=302)

    if not settings.LEMON_SQUEEZY_STORE_ID or not settings.LEMON_SQUEEZY_VARIANT_ID:
        raise HTTPException(status_code=503, detail="Payments not configured")

    payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "checkout_data": {
                    "custom": {
                        "user_id": str(user.id),
                    },
                },
                "product_options": {
                    "redirect_url": f"{settings.BASE_URL}/payment/success",
                },
            },
            "relationships": {
                "store": {
                    "data": {
                        "type": "stores",
                        "id": settings.LEMON_SQUEEZY_STORE_ID,
                    }
                },
                "variant": {
                    "data": {
                        "type": "variants",
                        "id": settings.LEMON_SQUEEZY_VARIANT_ID,
                    }
                },
            },
        }
    }

    resp = await client.post(
        f"{LEMONSQUEEZY_API}/checkouts",
        json=payload,
        headers={
            "Authorization": f"Bearer {settings.LEMON_SQUEEZY_KEY}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        },
    )

    if resp.status_code != 201:
        logger.error("Lemon Squeezy checkout failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail="Failed to create checkout session")

    checkout_url = resp.json()["data"]["attributes"]["url"]
    return RedirectResponse(url=checkout_url, status_code=303)


def _verify_webhook_signature(body: bytes, signature: str) -> bool:
    digest = hmac.new(
        settings.LEMON_SQUEEZY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature)


@router.post("/webhook")
async def lemon_squeezy_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    signature = request.headers.get("x-signature")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing signature")

    body = await request.body()
    if not _verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = json.loads(body)
    event_name = event.get("meta", {}).get("event_name")
    custom_data = event.get("meta", {}).get("custom_data", {})
    user_id = custom_data.get("user_id")
    attrs = event.get("data", {}).get("attributes", {})
    customer_id = str(attrs.get("customer_id", ""))

    if not user_id:
        logger.warning("Lemon Squeezy webhook missing user_id in custom_data")
        return {"status": "ignored"}

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning("Lemon Squeezy webhook for unknown user_id=%s", user_id)
        return {"status": "user_not_found"}

    if customer_id:
        user.lemon_squeezy_customer_id = customer_id

    if event_name in ("subscription_created", "subscription_resumed"):
        user.subscribed = True
        logger.info("User %s subscribed via Lemon Squeezy", user_id)

    elif event_name == "subscription_updated":
        status = attrs.get("status")
        user.subscribed = status in ("active", "on_trial")
        logger.info("User %s subscription updated: status=%s", user_id, status)

    elif event_name in ("subscription_cancelled", "subscription_expired"):
        user.subscribed = False
        logger.info("User %s subscription ended: %s", user_id, event_name)

    else:
        logger.info("Ignoring Lemon Squeezy event: %s", event_name)
        return {"status": "ignored"}

    await db.commit()
    return {"status": "ok"}


@router.get("/success", response_class=HTMLResponse)
async def payment_success(
    request: Request,
    user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "payment_success.html", context={
        "user": user,
    })
