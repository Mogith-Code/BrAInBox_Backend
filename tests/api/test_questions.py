"""Tests for the questions module. Owner: Udith."""

import uuid

import pytest
from sqlalchemy import delete

from api.core.security import CurrentUser
from shared.db.models import MCQOption, Question, User
from shared.enums import ContentStatus, QuestionType, UserRole
from tests.conftest import STUDENT, make_api_client

OTHER = CurrentUser(
    id=uuid.UUID(int=3), firebase_uid="test-other", email="other@test.local", role=UserRole.STUDENT
)


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


@pytest.mark.parametrize("limit", [0, 51])
async def test_topic_questions_limit_is_bounded(client, limit):
    response = await client.get(f"/api/v1/topics/{uuid.uuid4()}/questions?limit={limit}")
    assert response.status_code == 422


# --------------------------------------------------------------------------- visibility (DB)


@pytest.fixture
async def questions(db_session):  # type: ignore[no-untyped-def]
    """An approved bank question and another student's unreviewed AI question."""
    for u in (STUDENT, OTHER):
        if await db_session.get(User, u.id) is None:
            db_session.add(User(id=u.id, firebase_uid=u.firebase_uid, role=UserRole.STUDENT))
    rows = {}
    for name, status, owner in (
        ("approved", ContentStatus.APPROVED, None),
        ("others_draft", ContentStatus.PENDING_REVIEW, OTHER.id),
    ):
        q = Question(
            question_type=QuestionType.MCQ,
            stem=f"Where is ATP made? ({name})",
            explanation="In the mitochondrion.",
            status=status,
            source="ai",
            created_by=owner,
        )
        db_session.add(q)
        await db_session.flush()
        db_session.add(
            MCQOption(question_id=q.id, label="A", text="Mitochondrion", is_correct=True)
        )
        db_session.add(MCQOption(question_id=q.id, label="B", text="Ribosome", is_correct=False))
        rows[name] = q
    await db_session.commit()
    yield rows
    ids = [q.id for q in rows.values()]
    await db_session.execute(delete(Question).where(Question.id.in_(ids)))
    await db_session.execute(delete(User).where(User.id.in_([STUDENT.id, OTHER.id])))
    await db_session.commit()


@pytest.mark.db
async def test_question_visibility_and_hidden_answer(questions):
    async with make_api_client(user=STUDENT) as c:
        approved = await c.get(f"/api/v1/questions/{questions['approved'].id}")
        others = await c.get(f"/api/v1/questions/{questions['others_draft'].id}")
    async with make_api_client(user=OTHER) as c:
        own = await c.get(f"/api/v1/questions/{questions['others_draft'].id}")

    assert approved.status_code == 200
    body = approved.json()
    assert body["explanation"] is None  # it would give the answer away
    assert all("is_correct" not in o for o in body["options"])
    assert others.status_code == 404  # another student's unreviewed question stays hidden
    assert others.json()["error"]["code"] == "QUESTION_NOT_FOUND"
    assert own.status_code == 200  # the owner can still open it
