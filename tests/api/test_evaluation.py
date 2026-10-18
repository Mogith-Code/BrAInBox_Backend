"""Placeholder tests for the evaluation module. Owner: Keshomigha."""


async def test_evaluation_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/evaluation/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_evaluation_status_placeholder(client):
    response = await client.get("/api/v1/evaluation/status")
    assert response.status_code == 200
    assert response.json() == {"module": "evaluation", "status": "todo"}


# TODO(Keshomigha): add tests for every real endpoint of this module.
