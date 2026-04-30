from httpx import AsyncClient

from app.models.user import User


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
