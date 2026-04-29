from fastapi import Cookie, Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.config import get_settings
from app.db import get_db
from app.models.user import User

settings = get_settings()
serializer = URLSafeTimedSerializer(settings.SESSION_SECRET)

MAX_SESSION_AGE = 60 * 60 * 24 * 30  # 30 days


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


async def get_current_user(
    session: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user_id: int = serializer.loads(session, max_age=MAX_SESSION_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def create_session_cookie(user_id: int) -> str:
    return serializer.dumps(user_id)
