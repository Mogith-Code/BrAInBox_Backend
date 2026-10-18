"""Placeholder tests for the jobs module. Owner: shared."""


async def test_jobs_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/jobs/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_jobs_status_placeholder(client):
    response = await client.get("/api/v1/jobs/status")
    assert response.status_code == 200
    assert response.json() == {"module": "jobs", "status": "todo"}


# TODO(shared): add tests for every real endpoint of this module.
