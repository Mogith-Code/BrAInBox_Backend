"""Placeholder tests for the content module. Owner: Samni."""


async def test_content_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/content/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_content_status_placeholder(client):
    response = await client.get("/api/v1/content/status")
    assert response.status_code == 200
    assert response.json() == {"module": "content", "status": "todo"}


# TODO(Samni): add tests for every real endpoint of this module.
