import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.config import get_settings
from app.db import get_db
from app.dependencies import get_http_client
from app.models.activity import Activity
from app.models.user import User
from app.services import renamer

router = APIRouter(prefix="/webhook", tags=["webhook"])
settings = get_settings()
logger = logging.getLogger(__name__)


class StravaWebhookEvent(BaseModel):
    object_type: str
    object_id: int
    aspect_type: str
    owner_id: int
    subscription_id: int | None = None
    event_time: int | None = None


@router.get("")
async def verify_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
) -> dict[str, str]:
    if hub_verify_token != settings.STRAVA_VERIFY_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid verify token")
    return {"hub.challenge": hub_challenge}


@router.post("")
async def receive_event(
    event: StravaWebhookEvent,
    db: AsyncSession = Depends(get_db),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    if event.object_type != "activity" or event.aspect_type != "create":
        return {"status": "ignored"}

    result = await db.execute(select(User).where(User.strava_id == event.owner_id))
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning("Webhook for unknown strava_id=%s", event.owner_id)
        return {"status": "user_not_found"}

    if not user.auto_rename:
        return {"status": "auto_rename_disabled"}

    if not (user.beta_user or user.subscribed):
        return {"status": "not_authorized"}

    existing = await db.execute(
        select(Activity).where(Activity.strava_activity_id == event.object_id)
    )
    if existing.scalar_one_or_none() is not None:
        return {"status": "already_processed"}

    placeholder = Activity(
        user_id=user.id,
        strava_activity_id=event.object_id,
        generated_name="pending",
        raw_context={"claimed": True},
    )
    db.add(placeholder)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return {"status": "already_processed"}

    new_name = await renamer.rename_activity(event.object_id, user, db, client, placeholder)

    return {"status": "processed", "new_name": new_name}
