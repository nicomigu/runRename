from pathlib import Path

import logging

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user, get_http_client
from app.models.activity import Activity
from app.models.beta_code import BetaCode
from app.models.preference import Preference
from app.models.user import User

logger = logging.getLogger(__name__)

from app.template_globals import register_globals

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
register_globals(templates)


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Activity)
        .where(Activity.user_id == user.id)
        .order_by(Activity.created_at.desc())
        .limit(10)
    )
    activities = result.scalars().all()

    pref_result = await db.execute(
        select(Preference).where(Preference.user_id == user.id)
    )
    preference = pref_result.scalar_one_or_none()
    style = preference.style if preference else "poetic"

    can_rename = user.beta_user or user.subscribed

    return templates.TemplateResponse(request, "dashboard.html", context={
        "user": user,
        "activities": activities,
        "style": style,
        "can_rename": can_rename,
    })


@router.post("/toggle")
async def toggle_auto_rename(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not (user.beta_user or user.subscribed):
        raise HTTPException(status_code=403, detail="Subscription required")
    user.auto_rename = not user.auto_rename
    await db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/style")
async def update_style(
    style: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if style not in ("poetic", "funny", "minimal"):
        raise HTTPException(status_code=422, detail="Invalid style")
    result = await db.execute(
        select(Preference).where(Preference.user_id == user.id)
    )
    preference = result.scalar_one_or_none()
    if preference:
        preference.style = style
    else:
        db.add(Preference(user_id=user.id, style=style))
    await db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/delete-account")
async def delete_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    try:
        await client.post(
            "https://www.strava.com/oauth/deauthorize",
            params={"access_token": user.access_token},
        )
    except Exception:
        logger.warning("Failed to deauthorize with Strava for user %s", user.strava_id)

    await db.execute(delete(Activity).where(Activity.user_id == user.id))
    await db.execute(delete(Preference).where(Preference.user_id == user.id))
    await db.execute(
        update(BetaCode).where(BetaCode.used_by == user.id).values(used_by=None)
    )
    await db.delete(user)
    await db.commit()

    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session")
    return response
