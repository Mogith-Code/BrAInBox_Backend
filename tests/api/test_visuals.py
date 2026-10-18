"""Placeholder tests for the visuals module. Owner: Mogith."""


async def test_visuals_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/visuals/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_visuals_status_placeholder(client):
    response = await client.get("/api/v1/visuals/status")
    assert response.status_code == 200
    assert response.json() == {"module": "visuals", "status": "todo"}


# TODO(Mogith): add tests for every real endpoint of this module.
