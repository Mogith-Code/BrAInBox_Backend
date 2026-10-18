"""Placeholder tests for the syllabus module. Owner: Keshomigha."""


async def test_syllabus_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/syllabus/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_syllabus_status_placeholder(client):
    response = await client.get("/api/v1/syllabus/status")
    assert response.status_code == 200
    assert response.json() == {"module": "syllabus", "status": "todo"}


# TODO(Keshomigha): add tests for every real endpoint of this module.
