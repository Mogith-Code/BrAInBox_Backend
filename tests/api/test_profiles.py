"""Placeholder tests for the profiles module. Owner: Mogith."""


async def test_profiles_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/profiles/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_profiles_status_placeholder(client):
    response = await client.get("/api/v1/profiles/status")
    assert response.status_code == 200
    assert response.json() == {"module": "profiles", "status": "todo"}


# TODO(Mogith): add tests for every real endpoint of this module.
