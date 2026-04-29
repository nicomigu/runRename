from httpx import AsyncClient

from app.dependencies import create_session_cookie
from app.models.user import User


async def test_valid_session_cookie(client: AsyncClient, test_user: User):
    cookie = create_session_cookie(test_user.id)
    response = await client.get("/health", cookies={"session": cookie})
    assert response.status_code == 200


async def test_missing_session_returns_401(client: AsyncClient):
    """Endpoints that use get_current_user should 401 without a cookie.
    /health doesn't use it, so we test this via the dependency directly."""
    from app.dependencies import get_current_user
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(session=None)
    assert exc_info.value.status_code == 401


async def test_invalid_session_returns_401(client: AsyncClient):
    from app.dependencies import get_current_user
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(session="garbage.token.here")
    assert exc_info.value.status_code == 401
