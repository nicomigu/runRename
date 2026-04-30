import secrets
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.config import get_settings
from app.db import get_db
from app.dependencies import create_session_cookie, get_http_client
from app.models.user import User
from app.models.preference import Preference

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
state_serializer = URLSafeTimedSerializer(settings.SESSION_SECRET, salt="oauth-state")

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STATE_MAX_AGE = 600  # 10 minutes


@router.get("/strava")
async def strava_login(beta: str | None = Query(default=None)) -> RedirectResponse:
    is_beta = bool(beta and settings.BETA_INVITE_CODE and beta == settings.BETA_INVITE_CODE)
    signed_state = state_serializer.dumps({
        "nonce": secrets.token_hex(16),
        "beta": is_beta,
        "issued_at": int(time.time()),
    })
    params = urlencode({
        "client_id": settings.STRAVA_CLIENT_ID,
        "redirect_uri": f"{settings.BASE_URL}/auth/callback",
        "response_type": "code",
        "scope": "activity:read_all,activity:write",
        "state": signed_state,
    })
    return RedirectResponse(url=f"{STRAVA_AUTH_URL}?{params}")


@router.get("/callback")
async def strava_callback(
    code: str = Query(...),
    state: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    client: httpx.AsyncClient = Depends(get_http_client),
) -> RedirectResponse:
    try:
        state_data = state_serializer.loads(state, max_age=STATE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    is_beta = state_data.get("beta", False)

    token_response = await client.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": settings.STRAVA_CLIENT_ID,
            "client_secret": settings.STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
    )
    token_response.raise_for_status()
    token_data = token_response.json()

    athlete = token_data["athlete"]
    strava_id = athlete["id"]

    result = await db.execute(select(User).where(User.strava_id == strava_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            strava_id=strava_id,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_at=token_data["expires_at"],
            name=f'{athlete.get("firstname", "")} {athlete.get("lastname", "")}'.strip(),
            profile_pic=athlete.get("profile"),
            beta_user=is_beta,
            auto_rename=is_beta,
        )
        db.add(user)
        await db.flush()
        db.add(Preference(user_id=user.id))
    else:
        user.access_token = token_data["access_token"]
        user.refresh_token = token_data["refresh_token"]
        user.expires_at = token_data["expires_at"]
        user.name = f'{athlete.get("firstname", "")} {athlete.get("lastname", "")}'.strip()
        user.profile_pic = athlete.get("profile")
        if is_beta and not user.beta_user:
            user.beta_user = True
            user.auto_rename = True

    await db.commit()

    use_secure = settings.BASE_URL.startswith("https")
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="session",
        value=create_session_cookie(user.id),
        httponly=True,
        secure=use_secure,
        max_age=60 * 60 * 24 * 30,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("session")
    return response
