"""Admin knowledge base: model answers + keywords (knowledge_admin.py). Owner: Keshomigha."""

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


async def test_model_answer_create_list_and_keywords(admin_client, question) -> None:  # type: ignore[no-untyped-def]
    body = {
        "question_id": str(question["structured"]),
        "answer_text": "Water moves across a partially permeable membrane.",
        "source": "marking_scheme",
        "points": [
            {"text": "Movement of water", "marks": 1, "keywords": ["water", " Water "]},
            {"text": "Partially permeable membrane", "marks": 2},
        ],
    }
    created = await admin_client.post(ANSWERS, json=body)
    again = await admin_client.post(ANSWERS, json=body)
    assert created.status_code == 201, created.text
    answer = created.json()
    assert set(answer) == {"id", "question_id", "question_code", "question_stem", "answer_text",
                           "total_marks", "source", "status", "points", "updated_at"}  # fmt: skip
    assert answer["total_marks"] == 3
    assert answer["question_code"].startswith("Q-")
    assert [p["keywords"] for p in answer["points"]] == [["water"], []]
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "MODEL_ANSWER_EXISTS"

    listed = await admin_client.get(ANSWERS, params={"question_id": str(question["structured"])})
    assert [a["id"] for a in listed.json()] == [answer["id"]]

    point = answer["points"][1]["id"]
    updated = await admin_client.put(
        f"{ANSWERS}/{answer['id']}/keywords",
        json={"points": [{"point_id": point, "keywords": ["semi-permeable", "membrane"]}]},
    )
    foreign = await admin_client.put(
        f"{ANSWERS}/{answer['id']}/keywords",
        json={"points": [{"point_id": str(uuid.uuid4()), "keywords": ["x"]}]},
    )
    assert updated.status_code == 200
    assert updated.json()["points"][1]["keywords"] == ["membrane", "semi-permeable"]  # A-Z
    assert updated.json()["points"][0]["keywords"] == ["water"]  # untouched
    assert foreign.status_code == 422
    assert foreign.json()["error"]["code"] == "POINT_NOT_IN_ANSWER"


async def test_model_answer_404s(admin_client, admin_in_db) -> None:  # type: ignore[no-untyped-def]
    unknown_q = await admin_client.post(
        ANSWERS, json={"question_id": str(uuid.uuid4()), "answer_text": "x"}
    )
    unknown_a = await admin_client.put(
        f"{ANSWERS}/{uuid.uuid4()}/keywords",
        json={"points": [{"point_id": str(uuid.uuid4()), "keywords": []}]},
    )
    assert unknown_q.json()["error"]["code"] == "QUESTION_NOT_FOUND"
    assert unknown_a.status_code == 404
    assert unknown_a.json()["error"]["code"] == "MODEL_ANSWER_NOT_FOUND"


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", ANSWERS, {}),
        ("post", ANSWERS, {"json": {"question_id": str(uuid.uuid4()), "answer_text": "x"}}),
        ("put", f"{ANSWERS}/{uuid.uuid4()}/keywords", {"json": {"points": []}}),
    ],
)
async def test_login_and_admin_role_needed(anon_client, client, method, path, kwargs) -> None:  # type: ignore[no-untyped-def]
    assert (await getattr(anon_client, method)(path, **kwargs)).status_code == 401
    assert (await getattr(client, method)(path, **kwargs)).status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", ANSWERS, {"question_id": "nope", "answer_text": "x"}),
        ("post", ANSWERS, {"question_id": str(uuid.uuid4()), "answer_text": ""}),
        (
            "post",
            ANSWERS,
            {
                "question_id": str(uuid.uuid4()),
                "answer_text": "x",
                "points": [{"text": "p", "marks": 0}],
            },
        ),
        ("put", f"{ANSWERS}/{uuid.uuid4()}/keywords", {"points": []}),
    ],
)
async def test_bad_bodies_are_422(admin_client, method: str, path: str, body: dict) -> None:
    response = await getattr(admin_client, method)(path, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
