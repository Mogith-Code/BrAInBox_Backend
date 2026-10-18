"""Placeholder tests for the exams module. Owner: Udith."""


async def test_exams_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/exams/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_exams_status_placeholder(client):
    response = await client.get("/api/v1/exams/status")
    assert response.status_code == 200
    assert response.json() == {"module": "exams", "status": "todo"}


# TODO(Udith): add tests for every real endpoint of this module.
