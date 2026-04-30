from httpx import AsyncClient


async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_docs_available(client: AsyncClient):
    response = await client.get("/docs")
    assert response.status_code == 200
