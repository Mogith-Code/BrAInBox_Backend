"""Admin MCQ mapping: PUT /admin/options/{option_id}/misconception. Owner: Udith."""

import uuid

import pytest
from sqlalchemy import delete

from shared.db.models import (
    MCQOption,
    Misconception,
    Question,
)
from shared.enums import ContentStatus, QuestionType
from tests.conftest import ADMIN

ANSWERS = "/api/v1/admin/model-answers"
SOURCES = "/api/v1/admin/rag/sources"
REINDEX = "/api/v1/admin/rag/reindex"
TAG = "admextra"


def option_url(option_id: object) -> str:
    return f"/api/v1/admin/options/{option_id}/misconception"


@pytest.fixture
async def question(db_session, admin_in_db):  # type: ignore[no-untyped-def]
    """A structured question (for model answers) and an MCQ with options A (right), B (wrong)."""
    structured = Question(question_type=QuestionType.STRUCTURED, stem=f"Explain osmosis {TAG}",
                          source="admin", status=ContentStatus.APPROVED, created_by=ADMIN.id)  # fmt: skip
    mcq = Question(question_type=QuestionType.MCQ, stem=f"Which is a monomer? {TAG}",
                   source="admin", status=ContentStatus.APPROVED, created_by=ADMIN.id)  # fmt: skip
    db_session.add_all([structured, mcq])
    await db_session.flush()
    right = MCQOption(question_id=mcq.id, label="A", text="Glucose", is_correct=True)
    wrong = MCQOption(question_id=mcq.id, label="B", text="Starch", is_correct=False)
    db_session.add_all([right, wrong])
    await db_session.commit()
    ids = {"structured": structured.id, "mcq": mcq.id, "right": right.id, "wrong": wrong.id}
    yield ids
    await db_session.rollback()
    await db_session.execute(delete(Question).where(Question.created_by == ADMIN.id))
    await db_session.execute(delete(Misconception).where(Misconception.created_by == ADMIN.id))
    await db_session.commit()


async def test_option_misconception(admin_client, question, db_session) -> None:  # type: ignore[no-untyped-def]
    linked = await admin_client.put(
        option_url(question["wrong"]), json={"misconception": "  Thinks starch  is a monomer "}
    )
    right = await admin_client.put(option_url(question["right"]), json={"misconception": "x"})
    cleared = await admin_client.put(option_url(question["wrong"]), json={"misconception": None})
    unknown = await admin_client.put(option_url(uuid.uuid4()), json={"misconception": "x"})

    assert linked.status_code == 200
    assert linked.json() == {
        "option_id": str(question["wrong"]),
        "question_id": str(question["mcq"]),
        "question_code": linked.json()["question_code"],
        "label": "B",
        "text": "Starch",
        "is_correct": False,
        "misconception": "Thinks starch is a monomer",
    }
    assert right.status_code == 422
    assert right.json()["error"]["code"] == "CORRECT_OPTION_NO_MISCONCEPTION"
    assert cleared.json()["misconception"] is None
    assert unknown.json()["error"]["code"] == "OPTION_NOT_FOUND"


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [("put", option_url(uuid.uuid4()), {"json": {"misconception": "x"}})],
)
async def test_login_and_admin_role_needed(anon_client, client, method, path, kwargs) -> None:  # type: ignore[no-untyped-def]
    assert (await getattr(anon_client, method)(path, **kwargs)).status_code == 401
    assert (await getattr(client, method)(path, **kwargs)).status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", option_url(uuid.uuid4()), {"misconception": "x" * 201}),
        ("put", "/api/v1/admin/options/nope/misconception", {"misconception": "x"}),
    ],
)
async def test_bad_bodies_are_422(admin_client, method: str, path: str, body: dict) -> None:
    response = await getattr(admin_client, method)(path, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
