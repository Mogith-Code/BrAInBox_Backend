"""Placeholder tests for the questions module. Owner: Udith."""


async def test_questions_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/questions/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_questions_status_placeholder(client):
    response = await client.get("/api/v1/questions/status")
    assert response.status_code == 200
    assert response.json() == {"module": "questions", "status": "todo"}


# TODO(Udith): add tests for every real endpoint of this module.
