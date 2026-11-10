"""Tests for the mistake journal: recording wrong MCQ answers, listing and fixing them.
Owner: Keshomigha."""

import uuid

import pytest
from sqlalchemy import delete, select

from api.core.security import CurrentUser, get_current_user
from api.modules.performance import repository, service
from shared.db.models import MCQOption, Misconception
from shared.enums import MistakeType, UserRole
from tests.api.test_exams import FakeAIClient, _app_with, exam_data  # noqa: F401 (fixture)
from tests.api.test_performance import CELLS, GENETICS, Rows
from tests.conftest import STUDENT, _client

OTHER_STUDENT = CurrentUser(
    id=uuid.UUID(int=99), firebase_uid="other-student", email="o@test.local", role=UserRole.STUDENT
)

# --------------------------------------------------------------------------- recording (no DB)


def test_only_real_wrong_answers_are_mistakes():
    rows = Rows()
    rows.add(GENETICS, True)  # correct
    wrong = rows.add(GENETICS, False)
    rows.add(GENETICS, None, answered=False)  # unanswered
    rows.add(CELLS, False, option_of_other_question=True)  # unreliable answer
    rows.add(CELLS, None)  # answered, but never marked
    assert [r.response_id for r in service.wrong_answers(rows.rows)] == [wrong.response_id]


def test_mistake_type_comes_from_the_chosen_option():
    misconception = uuid.uuid4()
    rows = Rows()
    linked = rows.add(GENETICS, False, misconception_id=misconception)
    plain = rows.add(GENETICS, False)
    mistakes = service.build_mistakes(STUDENT.id, [linked, plain], {misconception: None}, {})
    assert mistakes[0].mistake_type == MistakeType.MISCONCEPTION
    assert mistakes[0].misconception_id == misconception
    assert mistakes[1].mistake_type == MistakeType.KNOWLEDGE_GAP
    assert mistakes[1].misconception_id is None
    assert all(m.user_id == STUDENT.id for m in mistakes)
    assert mistakes[1].response_id == plain.response_id


def test_mistake_concept_prefers_the_misconceptions_concept():
    misconception, its_concept, question_concept = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rows = Rows()
    both = rows.add(GENETICS, False, misconception_id=misconception)
    only_question = rows.add(GENETICS, False)
    neither = rows.add(GENETICS, False)
    mistakes = service.build_mistakes(
        STUDENT.id,
        [both, only_question, neither],
        {misconception: its_concept},
        {both.question_id: question_concept, only_question.question_id: question_concept},
    )
    assert [m.concept_id for m in mistakes] == [its_concept, question_concept, None]


# --------------------------------------------------------------------------- API (no DB)


async def test_mistakes_require_login(anon_client):
    assert (await anon_client.get("/api/v1/mistakes")).status_code == 401
    patched = await anon_client.patch(f"/api/v1/mistakes/{uuid.uuid4()}", json={"resolved": True})
    assert patched.status_code == 401


@pytest.mark.parametrize(
    "query",
    ["type=typo", "status=done", "unit_id=abc", "page=0", "size=101"],
)
async def test_list_mistakes_rejects_bad_filters(client, query):
    assert (await client.get(f"/api/v1/mistakes?{query}")).status_code == 422


@pytest.mark.parametrize("body", [{}, {"resolved": "maybe"}])
async def test_update_mistake_rejects_a_bad_body(client, body):
    response = await client.patch(f"/api/v1/mistakes/{uuid.uuid4()}", json=body)
    assert response.status_code == 422


async def test_update_unknown_mistake_is_not_found(client, monkeypatch):
    async def nothing(session, user_id, mistake_id):
        return None

    monkeypatch.setattr(repository, "get_mistake_row", nothing)
    response = await client.patch(f"/api/v1/mistakes/{uuid.uuid4()}", json={"resolved": True})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MISTAKE_NOT_FOUND"


# --------------------------------------------------------------------------- full flow (DB)


@pytest.mark.db
async def test_mistake_journal_after_submitting_a_paper(exam_data, db_session):  # noqa: F811
    """Generate + submit a paper through exams, record its mistakes, use the journal."""
    async with _client(_app_with(FakeAIClient())) as c:
        paper = (
            await c.post(
                "/api/v1/papers/generate",
                json={"topic_ids": [str(exam_data.id)], "num_questions": 5},
            )
        ).json()
        q = paper["questions"]
        answers = [{"question_id": q[0]["id"], "selected": "B"}]  # correct
        answers += [{"question_id": x["id"], "selected": "A"} for x in q[1:4]]  # 3 wrong
        answers += [{"question_id": q[4]["id"], "selected": None}]  # unanswered

        # The wrong option of one question is linked to a misconception.
        misconception = Misconception(title="Mistake journal test", correction_md="Fix it so.")
        db_session.add(misconception)
        await db_session.flush()
        option = (
            await db_session.execute(
                select(MCQOption).where(
                    MCQOption.question_id == uuid.UUID(q[1]["id"]), MCQOption.label == "A"
                )
            )
        ).scalar_one()
        option.misconception_id = misconception.id
        await db_session.commit()

        try:
            submitted = await c.post(
                f"/api/v1/papers/{paper['paper_id']}/submit",
                json={"answers": answers, "explain": False},
            )
            assert submitted.status_code == 200, submitted.text
            attempt_id = uuid.UUID(submitted.json()["attempt_id"])

            # ---- recording: wrong answers only, and only once
            assert await service.record_mistakes(db_session, STUDENT.id, attempt_id) == 3
            await db_session.commit()
            assert await service.record_mistakes(db_session, STUDENT.id, attempt_id) == 0
            # someone else can't record from this student's attempt
            assert await service.record_mistakes(db_session, OTHER_STUDENT.id, attempt_id) == 0

            # ---- the journal
            body = (await c.get("/api/v1/mistakes")).json()
            assert (body["total"], body["page"], body["pages"]) == (3, 1, 1)
            by_question = {m["question_id"]: m for m in body["items"]}
            assert set(by_question) == {x["id"] for x in q[1:4]}

            linked = by_question[q[1]["id"]]
            assert linked["mistake_type"] == "misconception"
            assert linked["misconception"]["title"] == "Mistake journal test"
            assert linked["correction"] == "Fix it so."
            assert linked["your_answer"] != linked["correct_answer"]
            assert linked["correct_answer"] == "Mitochondrion"
            assert linked["question"] == q[1]["question"]
            assert (linked["topic"], linked["source"]) == ("Test topic", "exam")
            assert linked["is_resolved"] is False

            plain = by_question[q[2]["id"]]
            assert plain["mistake_type"] == "knowledge_gap"
            assert plain["misconception"] is None

            # ---- filters and paging
            async def total(query: str) -> int:
                response = await c.get(f"/api/v1/mistakes?{query}")
                assert response.status_code == 200, response.text
                return response.json()["total"]

            assert await total("type=misconception") == 1
            assert await total("type=knowledge_gap") == 2
            assert await total("type=careless") == 0
            assert await total(f"unit_id={linked['unit_id']}") == 3
            assert await total(f"unit_id={uuid.uuid4()}") == 0
            page = (await c.get("/api/v1/mistakes?size=2&page=2")).json()
            assert (len(page["items"]), page["total"], page["pages"]) == (1, 3, 2)

            # ---- the "Fixed" toggle
            fixed = await c.patch(f"/api/v1/mistakes/{linked['id']}", json={"resolved": True})
            assert fixed.status_code == 200, fixed.text
            first_date = fixed.json()["resolved_at"]
            assert fixed.json()["is_resolved"] is True and first_date
            assert fixed.json()["correct_answer"] == "Mitochondrion"
            assert await total("status=resolved") == 1
            assert await total("status=open") == 2

            again = await c.patch(f"/api/v1/mistakes/{linked['id']}", json={"resolved": True})
            assert again.json()["resolved_at"] == first_date  # tapping twice keeps the first date

            reopened = await c.patch(f"/api/v1/mistakes/{linked['id']}", json={"resolved": False})
            assert reopened.json()["is_resolved"] is False
            assert reopened.json()["resolved_at"] is None
            assert await total("status=resolved") == 0

            # ---- another student sees nothing and can't change it
            other_app = _app_with(FakeAIClient())
            other_app.dependency_overrides[get_current_user] = lambda: OTHER_STUDENT
            async with _client(other_app) as other:
                assert (await other.get("/api/v1/mistakes")).json()["total"] == 0
                blocked = await other.patch(
                    f"/api/v1/mistakes/{linked['id']}", json={"resolved": True}
                )
                assert blocked.status_code == 404
                assert blocked.json()["error"]["code"] == "MISTAKE_NOT_FOUND"
        finally:
            option.misconception_id = None
            await db_session.commit()
            await db_session.execute(
                delete(Misconception).where(Misconception.id == misconception.id)
            )
            await db_session.commit()
