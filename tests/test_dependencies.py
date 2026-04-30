import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.dependencies import create_session_cookie, get_current_user
from app.models.user import User


async def test_valid_session_authenticates_dashboard(client: AsyncClient, test_user: User):
    cookie = create_session_cookie(test_user.id)
    response = await client.get("/dashboard", cookies={"session": cookie})
    assert response.status_code == 200
    assert test_user.name in response.text


async def test_missing_session_returns_401():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(session=None)
    assert exc_info.value.status_code == 401


async def test_invalid_session_returns_401():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(session="garbage.token.here")
    assert exc_info.value.status_code == 401
