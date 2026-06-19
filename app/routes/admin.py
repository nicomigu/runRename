import hmac
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.config import get_settings
from app.db import get_db
from app.dependencies import get_http_client
from app.models.activity import Activity
from app.models.beta_code import BetaCode
from app.models.user import User
from app.services import renamer

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()


def _check_admin(secret: str) -> None:
    if not hmac.compare_digest(secret, settings.ADMIN_SECRET):
        raise HTTPException(status_code=403, detail="Invalid admin secret")


@router.post("/beta")
async def grant_beta(
    strava_id: int = Query(...),
    x_admin_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    _check_admin(x_admin_secret)

    result = await db.execute(select(User).where(User.strava_id == strava_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.beta_user = True
    await db.commit()

    return {"status": "ok", "user": user.name, "beta_user": True}


@router.post("/rerename")
async def rerename_activity(
    activity_id: int = Query(..., description="Strava activity id to re-rename"),
    x_admin_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
    http_client: httpx.AsyncClient = Depends(get_http_client),
):
    _check_admin(x_admin_secret)

    result = await db.execute(
        select(Activity).where(Activity.strava_activity_id == activity_id)
    )
    activity_row = result.scalar_one_or_none()
    if activity_row is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    result = await db.execute(select(User).where(User.id == activity_row.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    new_name = await renamer.rename_activity(
        activity_id, user, db, http_client, activity_row
    )
    return {"status": "ok", "activity_id": activity_id, "new_name": new_name}


@router.post("/beta-codes")
async def generate_beta_codes(
    count: int = Query(default=1, ge=1, le=50),
    x_admin_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    _check_admin(x_admin_secret)

    codes = []
    for _ in range(count):
        code = secrets.token_urlsafe(8)
        db.add(BetaCode(code=code))
        codes.append(code)

    await db.commit()
    return {"codes": codes}


@router.get("/beta-codes")
async def list_beta_codes(
    x_admin_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    _check_admin(x_admin_secret)

    result = await db.execute(select(BetaCode).order_by(BetaCode.created_at.desc()))
    all_codes = result.scalars().all()

    return {
        "codes": [
            {
                "code": c.code,
                "used": c.used_by is not None,
                "used_by": c.used_by,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in all_codes
        ]
    }
