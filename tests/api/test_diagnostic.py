"""Onboarding diagnostic test (quizzes module). Owner: Udith."""

import uuid

import pytest
from sqlalchemy import delete, func, select

from api.core.errors import AppError, ServiceUnavailableError
from api.modules.quizzes.service import allocate_questions, unit_mastery, unit_status
from api.modules.syllabus.service import UnitInfo
from shared.db.models import MCQOption, Question, Topic, Unit, UnitMastery
from shared.enums import ContentStatus, QuestionType
from tests.conftest import STUDENT, make_api_client, student_claims

# --------------------------------------------------------------------------- pure logic


def units(n: int, weights: list[float] | None = None) -> list[UnitInfo]:
    return [
        UnitInfo(uuid.uuid4(), i + 1, f"Unit {i + 1}", (weights or [1.0] * n)[i]) for i in range(n)
    ]


def test_allocation_covers_every_unit_and_fills_to_15():
    us = units(10)
    allocation = allocate_questions(us, {u.id: 5 for u in us}, 15)
    assert sum(allocation.values()) == 15
    assert all(count >= 1 for count in allocation.values())


def test_allocation_follows_past_paper_weight():
    us = units(10, weights=[5, 1, 1, 1, 1, 1, 1, 1, 1, 1])
    allocation = allocate_questions(us, {u.id: 10 for u in us}, 15)
    assert allocation[us[0].id] == max(allocation.values())
    assert allocation[us[0].id] > 1


def test_allocation_respects_what_is_available():
    us = units(10)
    available = {u.id: 1 for u in us}
    available[us[3].id] = 6
    allocation = allocate_questions(us, available, 15)
    assert allocation[us[3].id] == 6 and sum(allocation.values()) == 15


@pytest.mark.parametrize(
    "available",
    [
        {},  # empty bank
        "one_unit_missing",
        "too_few",
    ],
)
def test_not_enough_questions(available):
    us = units(10)
    if available == "one_unit_missing":
        available = {u.id: 3 for u in us[:-1]}
    elif available == "too_few":
        available = {u.id: 1 for u in us}  # 10 < 15
    with pytest.raises(AppError) as err:
        allocate_questions(us, available, 15)
    assert err.value.code == "NOT_ENOUGH_QUESTIONS"


@pytest.mark.parametrize(
    ("correct", "asked", "expected"), [(0, 1, 25), (1, 1, 75), (2, 2, 83), (0, 2, 17), (1, 2, 50)]
)
def test_mastery_is_blended_with_50(correct, asked, expected):
    assert unit_mastery(correct, asked) == expected


def test_unit_status_thresholds():
    assert [unit_status(m) for m in (70, 69, 40, 39)] == ["strong", "ok", "ok", "needs_work"]


# --------------------------------------------------------------------------- database fixtures


class FakeAI:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.payloads: list[dict] = []

    async def sync(self, name, payload):  # type: ignore[no-untyped-def]
        self.payloads.append(payload)
        if self.fail:
            raise ServiceUnavailableError("ai_service down")
        if name == "next-action":
            return {"result": {"reason": "AI reason: revise this unit first."}}
        return {"result": {"summary": "AI says: strong in Unit 1, practise Unit 10."}}


@pytest.fixture
async def question_bank(db_session, student_in_db):
    """10 units (1 topic each) with 2-3 approved MCQs per unit (19 in total), plus noise:
    an outdated topic and an unapproved question that must never be picked."""
    if (await db_session.execute(select(func.count()).select_from(Unit))).scalar_one():
        pytest.skip("diagnostic tests need an empty test database (set TEST_DATABASE_URL)")
    created_units, question_ids = [], []
    for number in range(1, 11):
        unit = Unit(number=number, title=f"Unit title {number}")
        db_session.add(unit)
        await db_session.flush()
        topic = Topic(unit_id=unit.id, number=f"{number}.1", title=f"Topic {number}")
        outdated = Topic(unit_id=unit.id, number=f"{number}.9", title="Old", is_outdated=True)
        db_session.add_all([topic, outdated])
        await db_session.flush()
        created_units.append(unit.id)
        specs = [(topic, ContentStatus.APPROVED)] * (3 if number <= 2 else 2)
        specs += [(outdated, ContentStatus.APPROVED), (topic, ContentStatus.DRAFT)]
        for i, (t, status) in enumerate(specs):
            q = Question(
                topic_id=t.id,
                question_type=QuestionType.MCQ,
                stem=f"U{number} Q{i} {'OUTDATED' if t is outdated else status.value}",
                status=status,
            )
            db_session.add(q)
            await db_session.flush()
            question_ids.append(q.id)
            for label in "ABCD":
                db_session.add(
                    MCQOption(
                        question_id=q.id, label=label, text=f"opt {label}", is_correct=label == "B"
                    )
                )
    await db_session.commit()
    yield created_units
    await db_session.execute(delete(Question).where(Question.id.in_(question_ids)))
    await db_session.execute(delete(Unit).where(Unit.id.in_(created_units)))
    await db_session.commit()


def answer_letter(question: dict, letter: str) -> str:
    return next(o["id"] for o in question["options"] if o["label"] == letter)


# --------------------------------------------------------------------------- start / resume


@pytest.mark.db
async def test_start_gives_15_questions_over_10_units_without_answers(question_bank):
    async with make_api_client(user=STUDENT) as c:
        response = await c.post("/api/v1/diagnostic/start")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["total"], body["minutes"], body["answered"]) == (15, 10, 0)
    assert len(body["questions"]) == 15
    assert {q["unit_code"] for q in body["questions"]} == {str(n) for n in range(1, 11)}
    assert "correct" not in response.text and "is_correct" not in response.text
    assert all("OUTDATED" not in q["stem"] and "draft" not in q["stem"] for q in body["questions"])
    assert [o["label"] for o in body["questions"][0]["options"]] == ["A", "B", "C", "D"]


@pytest.mark.db
async def test_resume_returns_the_same_attempt(question_bank):
    async with make_api_client(user=STUDENT) as c:
        first = (await c.post("/api/v1/diagnostic/start")).json()
        q = first["questions"][0]
        saved = await c.post(
            f"/api/v1/diagnostic/{first['attempt_id']}/answer",
            json={"question_id": q["id"], "option_id": answer_letter(q, "A")},
        )
        changed = await c.post(
            f"/api/v1/diagnostic/{first['attempt_id']}/answer",
            json={"question_id": q["id"], "option_id": answer_letter(q, "B")},
        )
        again = (await c.post("/api/v1/diagnostic/start")).json()
    assert saved.json() == {"saved": True, "answered": 1, "total": 15}
    assert changed.json()["answered"] == 1  # changing an answer doesn't add one
    assert again["attempt_id"] == first["attempt_id"]
    assert again["answered"] == 1
    assert again["questions"][0]["selected_option_id"] == answer_letter(q, "B")


@pytest.mark.db
async def test_answer_validation(question_bank):
    async with make_api_client(user=STUDENT) as c:
        start = (await c.post("/api/v1/diagnostic/start")).json()
        q1, q2 = start["questions"][:2]
        wrong_option = await c.post(
            f"/api/v1/diagnostic/{start['attempt_id']}/answer",
            json={"question_id": q1["id"], "option_id": answer_letter(q2, "A")},
        )
        unknown_attempt = await c.post(
            f"/api/v1/diagnostic/{uuid.uuid4()}/answer",
            json={"question_id": q1["id"], "option_id": answer_letter(q1, "A")},
        )
    assert wrong_option.json()["error"]["code"] == "OPTION_INVALID"
    assert unknown_attempt.json()["error"]["code"] == "ATTEMPT_NOT_FOUND"


# --------------------------------------------------------------------------- submit / result


@pytest.mark.db
async def test_submit_computes_mastery_and_summary(question_bank, db_session):
    ai = FakeAI()
    async with make_api_client(user=STUDENT, claims=student_claims(), ai=ai) as c:
        start = (await c.post("/api/v1/diagnostic/start")).json()
        for q in start["questions"]:
            # Unit 1: all correct (B). Unit 10: unanswered. Others: wrong (A).
            if q["unit_code"] == "10":
                continue
            letter = "B" if q["unit_code"] == "1" else "A"
            await c.post(
                f"/api/v1/diagnostic/{start['attempt_id']}/answer",
                json={"question_id": q["id"], "option_id": answer_letter(q, letter)},
            )
        submitted = await c.post(f"/api/v1/diagnostic/{start['attempt_id']}/submit")
        latest = await c.get("/api/v1/diagnostic/result")
        resubmit = await c.post(f"/api/v1/diagnostic/{start['attempt_id']}/submit")
        me = await c.get("/api/v1/auth/me")

    assert submitted.status_code == 200, submitted.text
    result = submitted.json()
    unit1_asked = sum(1 for q in start["questions"] if q["unit_code"] == "1")
    assert result["score"] == unit1_asked
    assert result["total"] == 15
    assert result["strongest"]["unit_code"] == "1"
    units = {u["unit_code"]: u for u in result["units"]}
    assert units["1"]["mastery"] == unit_mastery(unit1_asked, unit1_asked)
    assert units["1"]["status"] == "strong"
    assert units["10"]["status"] == "needs_work"
    assert result["needs_work"]["unit_code"] in {
        u for u, v in units.items() if v["mastery"] == min(x["mastery"] for x in units.values())
    }
    assert result["summary"] == "AI says: strong in Unit 1, practise Unit 10."
    assert result["summary_ai_generated"] is True
    assert result["disclaimer"] == "Formative feedback — not an official exam mark."
    assert ai.payloads[0]["strongest"]["unit_code"] == "1"

    assert latest.json() == result
    assert resubmit.json()["error"]["code"] == "ATTEMPT_FINISHED"
    assert me.json()["onboarding"]["diagnostic_completed"] is True
    saved = (await db_session.execute(select(func.count()).select_from(UnitMastery))).scalar_one()
    assert saved == 10


@pytest.mark.db
async def test_summary_falls_back_when_ai_fails(question_bank):
    async with make_api_client(user=STUDENT, ai=FakeAI(fail=True)) as c:
        start = (await c.post("/api/v1/diagnostic/start")).json()
        result = (await c.post(f"/api/v1/diagnostic/{start['attempt_id']}/submit")).json()
    assert result["summary_ai_generated"] is False
    assert result["summary"]  # template sentence


@pytest.mark.db
async def test_result_before_any_diagnostic(student_in_db):
    async with make_api_client(user=STUDENT) as c:
        response = await c.get("/api/v1/diagnostic/result")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DIAGNOSTIC_NOT_FOUND"


@pytest.mark.db
async def test_not_enough_questions_with_an_empty_bank(student_in_db, db_session):
    if (await db_session.execute(select(func.count()).select_from(Unit))).scalar_one():
        pytest.skip("needs an empty test database")
    unit = Unit(number=1, title="Only unit")
    db_session.add(unit)
    await db_session.commit()
    try:
        async with make_api_client(user=STUDENT) as c:
            response = await c.post("/api/v1/diagnostic/start")
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "NOT_ENOUGH_QUESTIONS"
        assert "Unit 1" in error["message"]
    finally:
        await db_session.execute(delete(Unit).where(Unit.id == unit.id))
        await db_session.commit()


@pytest.mark.db
async def test_skip(student_in_db):
    async with make_api_client(user=STUDENT, claims=student_claims()) as c:
        skipped = await c.post("/api/v1/diagnostic/skip")
        me = await c.get("/api/v1/auth/me")
    assert skipped.json() == {"skipped": True}
    assert me.json()["onboarding"]["diagnostic_skipped"] is True
    assert me.json()["onboarding"]["diagnostic_completed"] is False
