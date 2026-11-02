"""Tests for the questions module. Owner: Udith."""

import uuid

from shared.db.models import MCQOption, Question, Topic, Unit
from shared.enums import ContentStatus, QuestionType


async def test_questions_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/questions/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_questions_status_placeholder(client):
    response = await client.get("/api/v1/questions/status")
    assert response.status_code == 200
    assert response.json() == {"module": "questions", "status": "todo"}


async def test_get_question_not_found(client):
    response = await client.get(f"/api/v1/questions/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "QUESTION_NOT_FOUND"


async def test_topic_questions_not_found(client):
    response = await client.get(f"/api/v1/topics/{uuid.uuid4()}/questions")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TOPIC_NOT_FOUND"

