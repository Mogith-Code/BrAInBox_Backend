"""POST /jobs/run and the /sync placeholders."""

from ai_service.routes.jobs import DISPATCH
from shared.enums import JobType


def test_every_job_type_has_a_pipeline():
    assert set(DISPATCH) == set(JobType)


async def test_run_placeholder_job(ai_client):
    response = await ai_client.post(
        "/jobs/run", json={"job_id": "j1", "job_type": "generate_notes", "payload": {}}
    )
    assert response.status_code == 200
    assert response.json()["result"] == {"status": "todo", "pipeline": "notes.generate_notes"}


async def test_unknown_job_type_is_rejected(ai_client):
    response = await ai_client.post("/jobs/run", json={"job_id": "j1", "job_type": "nope"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_sync_tag_post_placeholder(ai_client):
    response = await ai_client.post("/sync/tag-post", json={"title": "Osmosis?", "body": "Help"})
    assert response.status_code == 200
    assert response.json()["name"] == "tag-post"
