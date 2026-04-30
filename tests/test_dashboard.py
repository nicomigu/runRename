from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import create_session_cookie
from app.models.activity import Activity
from app.models.user import User


async def test_dashboard_requires_auth(client: AsyncClient):
    response = await client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 401


async def test_dashboard_renders_for_authenticated_user(
    client: AsyncClient, test_user: User
):
    cookie = create_session_cookie(test_user.id)
    response = await client.get("/dashboard", cookies={"session": cookie})
    assert response.status_code == 200
    assert "Dashboard" in response.text
    assert test_user.name in response.text


async def test_dashboard_shows_activities(
    client: AsyncClient, test_user: User, db: AsyncSession
):
    db.add(Activity(
        user_id=test_user.id,
        strava_activity_id=111,
        original_name="Morning Run",
        generated_name="Foggy dawn six before coffee",
    ))
    await db.commit()

    cookie = create_session_cookie(test_user.id)
    response = await client.get("/dashboard", cookies={"session": cookie})
    assert response.status_code == 200
    assert "Foggy dawn six before coffee" in response.text
    assert "Morning Run" in response.text


async def test_dashboard_shows_subscribe_cta_for_free_user(
    client: AsyncClient, test_user: User
):
    cookie = create_session_cookie(test_user.id)
    response = await client.get("/dashboard", cookies={"session": cookie})
    assert response.status_code == 200
    assert "Subscribe" in response.text


async def test_dashboard_no_subscribe_cta_for_beta_user(
    client: AsyncClient, test_user: User, db: AsyncSession
):
    test_user.beta_user = True
    await db.commit()

    cookie = create_session_cookie(test_user.id)
    response = await client.get("/dashboard", cookies={"session": cookie})
    assert response.status_code == 200
    assert "Unlock auto-renaming" not in response.text


async def test_toggle_requires_subscription(
    client: AsyncClient, test_user: User
):
    cookie = create_session_cookie(test_user.id)
    response = await client.post("/dashboard/toggle", cookies={"session": cookie}, follow_redirects=False)
    assert response.status_code == 403


async def test_toggle_works_for_beta_user(
    client: AsyncClient, test_user: User, db: AsyncSession
):
    test_user.beta_user = True
    await db.commit()
    assert test_user.auto_rename is False

    cookie = create_session_cookie(test_user.id)
    response = await client.post("/dashboard/toggle", cookies={"session": cookie}, follow_redirects=False)
    assert response.status_code == 303

    db.expire_all()
    await db.refresh(test_user)
    assert test_user.auto_rename is True


async def test_toggle_works_for_subscribed_user(
    client: AsyncClient, test_user: User, db: AsyncSession
):
    test_user.subscribed = True
    await db.commit()

    cookie = create_session_cookie(test_user.id)
    response = await client.post("/dashboard/toggle", cookies={"session": cookie}, follow_redirects=False)
    assert response.status_code == 303


async def test_style_update(client: AsyncClient, test_user: User, db: AsyncSession):
    cookie = create_session_cookie(test_user.id)
    response = await client.post(
        "/dashboard/style",
        data={"style": "funny"},
        cookies={"session": cookie},
        follow_redirects=False,
    )
    assert response.status_code == 303


async def test_style_invalid(client: AsyncClient, test_user: User):
    cookie = create_session_cookie(test_user.id)
    response = await client.post(
        "/dashboard/style",
        data={"style": "chaotic"},
        cookies={"session": cookie},
        follow_redirects=False,
    )
    assert response.status_code == 422


async def test_landing_page(client: AsyncClient):
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "Connect with Strava" in response.text


async def test_landing_redirects_when_logged_in(client: AsyncClient, test_user: User):
    cookie = create_session_cookie(test_user.id)
    response = await client.get("/", cookies={"session": cookie}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
