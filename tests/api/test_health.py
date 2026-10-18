"""GET /api/v1/health"""

import pytest

from api.core.database import get_session
from api.main import create_app
from tests.conftest import _client


class FakeSession:
    def __init__(self, fail: bool = False):
        self.fail = fail

    async def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.fail:
            raise ConnectionError("database down")


async def _health_with(session: FakeSession):  # type: ignore[no-untyped-def]
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    async with _client(app) as c:
        return await c.get("/api/v1/health")


async def test_health_ok():
    response = await _health_with(FakeSession())
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


async def test_health_reports_database_error():
    response = await _health_with(FakeSession(fail=True))
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "error"}


@pytest.mark.db
async def test_health_with_real_database(anon_client):
    response = await anon_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}
