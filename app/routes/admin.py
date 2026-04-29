import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()


@router.post("/beta")
async def grant_beta(
    strava_id: int = Query(...),
    x_admin_secret: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    if not hmac.compare_digest(x_admin_secret, settings.ADMIN_SECRET):
        raise HTTPException(status_code=403, detail="Invalid admin secret")

    result = await db.execute(select(User).where(User.strava_id == strava_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.beta_user = True
    await db.commit()

    return {"status": "ok", "user": user.name, "beta_user": True}
