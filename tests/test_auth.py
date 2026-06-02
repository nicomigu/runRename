from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import create_session_cookie
from app.models.beta_code import BetaCode
from app.models.user import User
from app.models.preference import Preference
from app.routes.auth import state_serializer

from tests.conftest import TestSession


def _make_signed_state(beta_code: str | None = None) -> str:
    return state_serializer.dumps({"nonce": "test", "beta_code": beta_code, "issued_at": 0})


async def test_strava_login_redirects(client: AsyncClient):
    response = await client.get("/auth/strava", follow_redirects=False)
    assert response.status_code == 307
    location = response.headers["location"]
    assert "strava.com/oauth/authorize" in location
    assert "client_id=" in location
    parsed = urlparse(location)
    qs = parse_qs(parsed.query)
    state_data = state_serializer.loads(qs["state"][0], max_age=60)
    assert state_data["beta_code"] is None


async def test_callback_creates_user(client: AsyncClient, db: AsyncSession):
    state = _make_signed_state()
    response = await client.get(
        f"/auth/callback?code=test_code&state={state}", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    assert "session" in response.cookies

    result = await db.execute(select(User).where(User.strava_id == 12345))
    user = result.scalar_one()
    assert user.name == "Nico Runner"
    assert user.access_token == "new_access_token"

    result = await db.execute(select(Preference).where(Preference.user_id == user.id))
    pref = result.scalar_one()
    assert pref.style == "poetic"


async def test_callback_updates_existing_user(
    client: AsyncClient, db: AsyncSession, test_user: User
):
    state = _make_signed_state()
    response = await client.get(
        f"/auth/callback?code=test_code&state={state}", follow_redirects=False
    )
    assert response.status_code == 302

    db.expire_all()
    result = await db.execute(select(User).where(User.strava_id == 12345))
    user = result.scalar_one()
    assert user.access_token == "new_access_token"
    assert user.refresh_token == "new_refresh_token"

    pref_count = await db.execute(select(Preference).where(Preference.user_id == user.id))
    prefs = pref_count.scalars().all()
    assert len(prefs) == 1


async def test_callback_with_valid_beta_code(client: AsyncClient, db: AsyncSession):
    beta = BetaCode(code="SINGLE-USE-1")
    db.add(beta)
    await db.commit()

    state = _make_signed_state(beta_code="SINGLE-USE-1")
    response = await client.get(
        f"/auth/callback?code=test_code&state={state}", follow_redirects=False
    )
    assert response.status_code == 302

    async with TestSession() as db2:
        result = await db2.execute(select(User).where(User.strava_id == 12345))
        user = result.scalar_one()
        assert user.beta_user is True
        assert user.auto_rename is True

        result = await db2.execute(select(BetaCode).where(BetaCode.code == "SINGLE-USE-1"))
        code = result.scalar_one()
        assert code.used_by == user.id
        assert code.used_at is not None


async def test_callback_without_beta_code(client: AsyncClient, db: AsyncSession):
    state = _make_signed_state()
    response = await client.get(
        f"/auth/callback?code=test_code&state={state}", follow_redirects=False
    )
    assert response.status_code == 302

    result = await db.execute(select(User).where(User.strava_id == 12345))
    user = result.scalar_one()
    assert user.beta_user is False
    assert user.auto_rename is False


async def test_callback_with_already_used_code(client: AsyncClient, db: AsyncSession, test_user: User):
    from datetime import datetime
    beta = BetaCode(code="USED-CODE", used_by=test_user.id, used_at=datetime.utcnow())
    db.add(beta)
    await db.commit()

    new_user_state = _make_signed_state(beta_code="USED-CODE")
    response = await client.get(
        f"/auth/callback?code=test_code&state={new_user_state}", follow_redirects=False
    )
    assert response.status_code == 302

    async with TestSession() as db2:
        result = await db2.execute(select(User).where(User.strava_id == 12345))
        user = result.scalar_one()
        assert user.beta_user is False


async def test_callback_with_forged_state_returns_400(client: AsyncClient):
    response = await client.get(
        "/auth/callback?code=test_code&state=beta", follow_redirects=False
    )
    assert response.status_code == 400


async def test_callback_with_missing_state_returns_400(client: AsyncClient):
    response = await client.get("/auth/callback?code=test_code", follow_redirects=False)
    assert response.status_code == 400


async def test_strava_login_with_valid_beta_code(client: AsyncClient, db: AsyncSession):
    beta = BetaCode(code="VALID-CODE")
    db.add(beta)
    await db.commit()

    response = await client.get("/auth/strava?beta=VALID-CODE", follow_redirects=False)
    location = response.headers["location"]
    parsed = urlparse(location)
    qs = parse_qs(parsed.query)
    state_data = state_serializer.loads(qs["state"][0], max_age=60)
    assert state_data["beta_code"] == "VALID-CODE"


async def test_strava_login_with_invalid_beta_code(client: AsyncClient):
    response = await client.get("/auth/strava?beta=WRONG", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/?error=invalid_beta_code"


async def test_callback_beta_applied_on_repeat_login(
    client: AsyncClient, db: AsyncSession, test_user: User
):
    assert test_user.beta_user is False

    beta = BetaCode(code="REPEAT-CODE")
    db.add(beta)
    await db.commit()

    state = _make_signed_state(beta_code="REPEAT-CODE")
    response = await client.get(
        f"/auth/callback?code=test_code&state={state}", follow_redirects=False
    )
    assert response.status_code == 302

    async with TestSession() as db2:
        result = await db2.execute(select(User).where(User.strava_id == 12345))
        user = result.scalar_one()
        assert user.beta_user is True
        assert user.auto_rename is True


async def test_logout_clears_cookie(client: AsyncClient):
    response = await client.get("/auth/logout", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    set_cookie = response.headers.get("set-cookie", "")
    assert "session" in set_cookie
    assert "Max-Age=0" in set_cookie or "expires" in set_cookie.lower()
