from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.beta_code import BetaCode
from app.models.user import User

from tests.conftest import TestSession


async def test_grant_beta_success(client: AsyncClient, test_user: User):
    assert test_user.beta_user is False

    response = await client.post(
        f"/admin/beta?strava_id={test_user.strava_id}",
        headers={"x-admin-secret": "test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["beta_user"] is True
    assert data["user"] == test_user.name


async def test_grant_beta_wrong_secret(client: AsyncClient, test_user: User):
    response = await client.post(
        f"/admin/beta?strava_id={test_user.strava_id}",
        headers={"x-admin-secret": "wrong"},
    )
    assert response.status_code == 403


async def test_grant_beta_missing_secret(client: AsyncClient, test_user: User):
    response = await client.post(f"/admin/beta?strava_id={test_user.strava_id}")
    assert response.status_code == 422


async def test_grant_beta_unknown_user(client: AsyncClient):
    response = await client.post(
        "/admin/beta?strava_id=99999",
        headers={"x-admin-secret": "test"},
    )
    assert response.status_code == 404


async def test_generate_beta_codes(client: AsyncClient):
    response = await client.post(
        "/admin/beta-codes?count=3",
        headers={"x-admin-secret": "test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["codes"]) == 3
    assert len(set(data["codes"])) == 3


async def test_generate_beta_codes_wrong_secret(client: AsyncClient):
    response = await client.post(
        "/admin/beta-codes?count=1",
        headers={"x-admin-secret": "wrong"},
    )
    assert response.status_code == 403


async def test_list_beta_codes(client: AsyncClient, db: AsyncSession):
    db.add(BetaCode(code="LIST-TEST-1"))
    db.add(BetaCode(code="LIST-TEST-2"))
    await db.commit()

    response = await client.get(
        "/admin/beta-codes",
        headers={"x-admin-secret": "test"},
    )
    assert response.status_code == 200
    data = response.json()
    codes = [c["code"] for c in data["codes"]]
    assert "LIST-TEST-1" in codes
    assert "LIST-TEST-2" in codes
    assert all(c["used"] is False for c in data["codes"])
