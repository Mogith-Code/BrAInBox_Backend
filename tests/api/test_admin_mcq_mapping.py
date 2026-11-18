"""Admin MCQ mapping: PUT /admin/options/{option_id}/misconception, and the AI suggestions
(POST /admin/questions/{id}/misconception-suggestions). Owner: Udith."""

import uuid

import pytest
from sqlalchemy import delete

from shared.db.models import (
    AIJob,
    MCQOption,
    Misconception,
    Question,
)
from shared.enums import ContentStatus, JobType, QuestionType
from tests.conftest import ADMIN, make_api_client

ANSWERS = "/api/v1/admin/model-answers"
SOURCES = "/api/v1/admin/rag/sources"
REINDEX = "/api/v1/admin/rag/reindex"
TAG = "admextra"


def option_url(option_id: object) -> str:
    return f"/api/v1/admin/options/{option_id}/misconception"


def suggest_url(question_id: object) -> str:
    return f"/api/v1/admin/questions/{question_id}/misconception-suggestions"


class MappingAI:
    """Stands in for the ai_service: answers MAP_MISCONCEPTIONS with `answer(payload)`."""

    def __init__(self, answer):  # type: ignore[no-untyped-def]
        self.answer = answer
        self.payloads: list[dict] = []

    async def run_job(self, job_id, job_type, payload):  # type: ignore[no-untyped-def]
        assert job_type == JobType.MAP_MISCONCEPTIONS.value
        self.payloads.append(payload)
        return {"job_id": job_id, "job_type": job_type, "result": self.answer(payload)}


async def _delete_mapping_jobs(db_session) -> None:  # type: ignore[no-untyped-def]
    await db_session.rollback()
    await db_session.execute(
        delete(AIJob).where(
            AIJob.requested_by == ADMIN.id, AIJob.job_type == JobType.MAP_MISCONCEPTIONS
        )
    )
    await db_session.commit()


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


# --------------------------------------------------------------------------- AI suggestions


@pytest.mark.db
async def test_ai_suggestions_are_listed_but_not_saved(question, db_session) -> None:  # type: ignore[no-untyped-def]
    known = Misconception(title=f"Thinks starch is a monomer {TAG}", created_by=ADMIN.id)
    db_session.add(known)
    await db_session.commit()

    def answer(payload: dict) -> dict:
        return {
            "mappings": [
                {"option_label": "B", "misconception_id": str(known.id),
                 "new_misconception_title": None, "similarity": 1.0},
                {"option_label": "A", "misconception_id": None,  # the right answer: dropped
                 "new_misconception_title": "Nothing wrong", "similarity": 0.0},
            ],
            "prompt_version": "questions/map_misconceptions.v1",
        }  # fmt: skip

    ai = MappingAI(answer)
    try:
        async with make_api_client(user=ADMIN, ai=ai) as admin:
            queued = await admin.post(suggest_url(question["mcq"]))
            assert queued.status_code == 202, queued.text
            assert queued.json()["question_id"] == str(question["mcq"])
            job = (await admin.get(f"/api/v1/jobs/{queued.json()['job_id']}")).json()
            structured = await admin.post(suggest_url(question["structured"]))
            unknown = await admin.post(suggest_url(uuid.uuid4()))

        [payload] = ai.payloads
        assert payload["question"]["options"] == [
            {"label": "A", "text": "Glucose", "is_correct": True},
            {"label": "B", "text": "Starch", "is_correct": False},
        ]
        assert {"id": str(known.id), "title": known.title} in payload["misconceptions"]
        assert job["status"] == "succeeded", job
        assert job["result"]["suggestions"] == [
            {
                "option_id": str(question["wrong"]),
                "label": "B",
                "option_text": "Starch",
                "current_misconception": None,
                "suggested_misconception": known.title,
                "misconception_id": str(known.id),
                "is_new": False,
                "similarity": 1.0,
            }
        ]
        # Suggestions only: the option stays unlinked until the admin confirms it.
        option = await db_session.get(MCQOption, question["wrong"])
        await db_session.refresh(option)
        assert option.misconception_id is None
        assert (structured.status_code, structured.json()["error"]["code"]) == (422, "NOT_AN_MCQ")
        assert unknown.json()["error"]["code"] == "QUESTION_NOT_FOUND"
    finally:
        await _delete_mapping_jobs(db_session)


@pytest.mark.db
async def test_new_misconception_titles_are_suggested_as_new(question, db_session) -> None:  # type: ignore[no-untyped-def]
    def answer(payload: dict) -> dict:
        return {"mappings": [{"option_label": "B", "misconception_id": None,
                              "new_misconception_title": "  Confuses  monomer and polymer ",
                              "similarity": 0.4}]}  # fmt: skip

    try:
        async with make_api_client(user=ADMIN, ai=MappingAI(answer)) as admin:
            queued = await admin.post(suggest_url(question["mcq"]))
            job = (await admin.get(f"/api/v1/jobs/{queued.json()['job_id']}")).json()
        [suggestion] = job["result"]["suggestions"]
        assert suggestion["suggested_misconception"] == "Confuses monomer and polymer"
        assert (suggestion["is_new"], suggestion["misconception_id"]) == (True, None)
    finally:
        await _delete_mapping_jobs(db_session)


async def test_suggestions_need_the_admin_role(anon_client, client) -> None:  # type: ignore[no-untyped-def]
    assert (await anon_client.post(suggest_url(uuid.uuid4()))).status_code == 401
    assert (await client.post(suggest_url(uuid.uuid4()))).status_code == 403
