"""Placeholder tests for the performance module. Owner: Keshomigha."""


async def test_performance_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/performance/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_performance_status_placeholder(client):
    response = await client.get("/api/v1/performance/status")
    assert response.status_code == 200
    assert response.json() == {"module": "performance", "status": "todo"}


# TODO(Keshomigha): add tests for every real endpoint of this module.
