"""Placeholder tests for the auth module. Owner: Mogith."""


async def test_auth_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/auth/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_auth_status_placeholder(client):
    response = await client.get("/api/v1/auth/status")
    assert response.status_code == 200
    assert response.json() == {"module": "auth", "status": "todo"}


# TODO(Mogith): add tests for every real endpoint of this module.
