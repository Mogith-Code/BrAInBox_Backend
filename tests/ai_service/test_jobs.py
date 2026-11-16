"""POST /jobs/run and the /sync placeholders."""

from ai_service.routes.jobs import DISPATCH
from shared.enums import JobType


def test_every_job_type_has_a_pipeline():
    assert set(DISPATCH) == set(JobType)


async def test_run_notes_job_with_the_mock_llm(ai_client):
    payload = {"topic_title": "Mendelian inheritance", "depth": "quick"}
    response = await ai_client.post(
        "/jobs/run", json={"job_id": "j1", "job_type": "generate_notes", "payload": payload}
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["type"] == "full" and result["blocks"][0]["type"] == "heading"


async def test_notes_job_without_a_topic_is_an_input_error(ai_client):
    response = await ai_client.post(
        "/jobs/run", json={"job_id": "j1", "job_type": "generate_notes", "payload": {}}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MISSING_TOPIC_TITLE"


async def test_unknown_job_type_is_rejected(ai_client):
    response = await ai_client.post("/jobs/run", json={"job_id": "j1", "job_type": "nope"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_sync_tag_post_placeholder(ai_client):
    response = await ai_client.post("/sync/tag-post", json={"title": "Osmosis?", "body": "Help"})
    assert response.status_code == 200
    assert response.json()["name"] == "tag-post"
