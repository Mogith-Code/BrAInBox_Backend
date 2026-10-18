"""Tests for the exams module: Udith's paper generation + evaluation. Owner: Udith."""

import random
import uuid

import pytest
from sqlalchemy import delete

from api.core.ai_client import get_ai_client
from api.core.errors import ServiceUnavailableError
from api.core.security import get_current_user
from api.main import create_app
from api.modules.exams.service import GradingQuestion, evaluate_paper, option_from_letter
from shared.db.models import AIJob, Paper, Question, Topic, Unit, User
from shared.enums import UserRole
from tests.conftest import STUDENT, _client

# --------------------------------------------------------------------------- placeholders


async def test_exams_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/exams/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_exams_status_placeholder(client):
    response = await client.get("/api/v1/exams/status")
    assert response.status_code == 200
    assert response.json() == {"module": "exams", "status": "todo"}


# --------------------------------------------------------------------------- marking (no DB)

OPTIONS = ["Ribosome", "Mitochondrion", "Golgi apparatus", "Lysosome", "Nucleus"]


def make_question(topic: str = "Cells", correct: str = "Mitochondrion", marks: int = 1):
    return GradingQuestion(uuid.uuid4(), topic, "Where is ATP made?", OPTIONS, correct, marks)


def test_option_from_letter():
    q = make_question()
    assert option_from_letter(q, "B") == "Mitochondrion"
    assert option_from_letter(q, " b ") == "Mitochondrion"
    assert option_from_letter(q, "Z") is None
    assert option_from_letter(q, "") is None
    assert option_from_letter(q, None) is None


def test_evaluate_paper_scores_topics_and_weak_topics():
    cells = [make_question("Cells"), make_question("Cells", marks=2)]
    plants = [make_question("Photosynthesis"), make_question("Photosynthesis")]
    chosen = {
        cells[0].id: "B",  # correct
        cells[1].id: "B",  # correct, 2 marks
        plants[0].id: "A",  # wrong
        # plants[1] not answered
    }
    result = evaluate_paper(uuid.uuid4(), cells + plants, chosen)

    assert (result.total_questions, result.answered, result.correct) == (4, 3, 2)
    assert (result.marks_obtained, result.marks_total, result.percent) == (3, 5, 60.0)
    assert {t.topic: t.percent for t in result.by_topic} == {"Cells": 100.0, "Photosynthesis": 0.0}
    assert result.weak_topics == ["Photosynthesis"]
    assert result.results[2].selected_option == "Ribosome"
    assert result.results[3].selected_option is None
    assert result.results[3].marks_awarded == 0


def test_evaluate_empty_paper():
    result = evaluate_paper(uuid.uuid4(), [], {})
    assert result.percent == 0.0
    assert result.weak_topics == []


async def test_generate_needs_at_least_one_topic(client):
    response = await client.post("/api/v1/papers/generate", json={"topic_ids": []})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------------------------- full flow (DB)


class FakeAIClient:
    """Stands in for the ai_service: BUILD_PAPER returns fixed questions, explanations echo."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[str] = []

    async def run_job(self, job_id, job_type, payload):  # type: ignore[no-untyped-def]
        self.calls.append(job_type)
        if self.fail:
            raise ServiceUnavailableError("ai_service down")
        questions = [
            {
                "question": f"Question {i} about {topic['title']}?",
                "options": OPTIONS,
                "correct_answer": "Mitochondrion",  # = letter B
                "explanation": "",
                "marks": 1,
                "topic_id": topic["topic_id"],
            }
            for topic in payload["topics"]
            for i in range(payload["num_questions"])
        ]
        result = {"questions": questions, "warnings": [], "prompt_version": "test.v1"}
        return {"job_id": job_id, "job_type": job_type, "result": result}

    async def sync(self, name, payload):  # type: ignore[no-untyped-def]
        self.calls.append(name)
        explanations = {i["question_id"]: "Because ATP is made there." for i in payload["items"]}
        return {"name": name, "status": "ok", "result": {"explanations": explanations}}


@pytest.fixture
async def exam_data(db_session):
    """A student user + one unit/topic in the database; everything is removed afterwards."""
    user = await db_session.get(User, STUDENT.id)
    if user is None:
        user = User(id=STUDENT.id, firebase_uid=STUDENT.firebase_uid, role=UserRole.STUDENT)
        db_session.add(user)
    unit = Unit(number=random.randint(1000, 999_999), title="Test unit")
    db_session.add(unit)
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="T.1", title="Test topic")
    db_session.add(topic)
    await db_session.commit()
    yield topic
    for stmt in (
        delete(Question).where(Question.created_by == STUDENT.id),
        delete(Paper).where(Paper.created_by == STUDENT.id),
        delete(AIJob).where(AIJob.requested_by == STUDENT.id),
        delete(User).where(User.id == STUDENT.id),
        delete(Unit).where(Unit.id == unit.id),
    ):
        await db_session.execute(stmt)
    await db_session.commit()


def _app_with(ai: FakeAIClient):  # type: ignore[no-untyped-def]
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: STUDENT
    app.dependency_overrides[get_ai_client] = lambda: ai
    return app


@pytest.mark.db
async def test_generate_and_submit_paper(exam_data):
    ai = FakeAIClient()
    async with _client(_app_with(ai)) as c:
        generated = await c.post(
            "/api/v1/papers/generate", json={"topic_ids": [str(exam_data.id)], "num_questions": 2}
        )
        assert generated.status_code == 200, generated.text
        paper = generated.json()
        assert paper["total_questions"] == 2
        assert paper["questions"][0]["topic"] == "Test topic"
        assert "correct_answer" not in paper["questions"][0]  # answers stay on the server

        q1, q2 = paper["questions"]
        submitted = await c.post(
            f"/api/v1/papers/{paper['paper_id']}/submit",
            json={
                "answers": [
                    {"question_id": q1["id"], "selected": "B"},
                    {"question_id": q2["id"], "selected": "A"},
                ]
            },
        )
        assert submitted.status_code == 200, submitted.text
        result = submitted.json()
        assert (result["correct"], result["marks_obtained"], result["percent"]) == (1, 1, 50.0)
        assert result["attempt_id"]
        assert result["weak_topics"] == ["Test topic"]
        wrong = result["results"][1]
        assert wrong["selected_option"] == "Ribosome"
        assert wrong["explanation"] == "Because ATP is made there."
        assert result["results"][0]["explanation"] is None  # right answers need no explanation

    assert ai.calls == ["build_paper", "explain-mcq"]


@pytest.mark.db
async def test_generate_with_unknown_topic(exam_data):
    async with _client(_app_with(FakeAIClient())) as c:
        response = await c.post("/api/v1/papers/generate", json={"topic_ids": [str(uuid.uuid4())]})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TOPIC_NOT_FOUND"


@pytest.mark.db
async def test_generate_when_ai_service_fails(exam_data):
    async with _client(_app_with(FakeAIClient(fail=True))) as c:
        response = await c.post("/api/v1/papers/generate", json={"topic_ids": [str(exam_data.id)]})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_GENERATION_FAILED"


@pytest.mark.db
async def test_submit_unknown_paper(exam_data):
    async with _client(_app_with(FakeAIClient())) as c:
        response = await c.post(f"/api/v1/papers/{uuid.uuid4()}/submit", json={"answers": []})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PAPER_NOT_FOUND"
