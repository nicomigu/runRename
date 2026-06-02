import hmac
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models.beta_code import BetaCode
from app.models.user import User

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
