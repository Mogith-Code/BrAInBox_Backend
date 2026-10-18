"""Placeholder tests for the quizzes module. Owner: Udith."""


async def test_quizzes_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/quizzes/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_quizzes_status_placeholder(client):
    response = await client.get("/api/v1/quizzes/status")
    assert response.status_code == 200
    assert response.json() == {"module": "quizzes", "status": "todo"}


# TODO(Udith): add tests for every real endpoint of this module.
