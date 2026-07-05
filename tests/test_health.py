import pytest
from httpx import AsyncClient
from httpx import ASGITransport

from app.main import app


@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/v1/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
