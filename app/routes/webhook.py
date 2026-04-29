import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.config import get_settings
from app.db import get_db
from app.dependencies import get_http_client
from app.models.user import User
from app.services import renamer

router = APIRouter(prefix="/webhook", tags=["webhook"])
settings = get_settings()
logger = logging.getLogger(__name__)


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
    request: Request,
    db: AsyncSession = Depends(get_db),
    client: httpx.AsyncClient = Depends(get_http_client),
) -> dict[str, str]:
    body = await request.json()

    if body.get("object_type") != "activity" or body.get("aspect_type") != "create":
        return {"status": "ignored"}

    owner_id = body.get("owner_id")
    activity_id = body.get("object_id")

    result = await db.execute(select(User).where(User.strava_id == owner_id))
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning("Webhook for unknown strava_id=%s", owner_id)
        return {"status": "user_not_found"}

    if not user.auto_rename:
        return {"status": "auto_rename_disabled"}

    if not (user.beta_user or user.subscribed):
        return {"status": "not_authorized"}

    new_name = await renamer.rename_activity(activity_id, user, db, client)

    return {"status": "processed", "new_name": new_name}
