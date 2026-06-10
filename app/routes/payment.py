import logging
from pathlib import Path

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/payment", tags=["payment"])
settings = get_settings()
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

stripe.api_key = settings.STRIPE_SECRET_KEY


@router.get("/checkout")
async def checkout(
    user: User = Depends(get_current_user),
):
    if user.beta_user or user.subscribed:
        return RedirectResponse(url="/dashboard", status_code=302)

    if not settings.STRIPE_PRICE_ID:
        raise HTTPException(status_code=503, detail="Payments not configured")

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": settings.STRIPE_PRICE_ID, "quantity": 1}],
        success_url=f"{settings.BASE_URL}/payment/success",
        cancel_url=f"{settings.BASE_URL}/dashboard",
        client_reference_id=str(user.id),
        customer=user.stripe_customer_id or None,
    )

    return RedirectResponse(url=session.url, status_code=303)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()
    sig = request.headers.get("stripe-signature")
    if not sig:
        raise HTTPException(status_code=401, detail="Missing signature")

    try:
        event = stripe.Webhook.construct_event(
            body, sig, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=401, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        user_id = data.get("client_reference_id")
        customer_id = data.get("customer")
        if not user_id:
            logger.warning("Stripe checkout.session.completed missing client_reference_id")
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

    if event_type in (
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        customer_id = data.get("customer")
        status = data.get("status")

        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            logger.warning("Stripe webhook for unknown customer=%s", customer_id)
            return {"status": "user_not_found"}

        user.subscribed = status in ("active", "trialing")
        await db.commit()
        logger.info("User %s subscription %s: status=%s", user.id, event_type, status)
        return {"status": "ok"}

    logger.info("Ignoring Stripe event: %s", event_type)
    return {"status": "ignored"}


@router.get("/success", response_class=HTMLResponse)
async def payment_success(
    request: Request,
    user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "payment_success.html", context={
        "user": user,
    })
