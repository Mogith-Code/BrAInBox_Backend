"""Practice quizzes with instant feedback (quizzes module)."""

import random
import uuid

import pytest
from sqlalchemy import delete, func, select

from api.modules.performance.service import mastery_level, mcq_mistake_type, next_mastery
from api.modules.quizzes.repository import QuizRow
from api.modules.quizzes.service import pick_questions, quiz_minutes
from shared.db.models import (
    Concept,
    ConceptMastery,
    MCQOption,
    Misconception,
    Mistake,
    Question,
    QuestionConcept,
    Topic,
    Unit,
    UnitMastery,
)
from shared.enums import ContentStatus, MistakeType, QuestionType
from tests.conftest import STUDENT, make_api_client

# --------------------------------------------------------------------------- pure logic


def test_mastery_moving_average():
    assert next_mastery(0.5, 1.0) == 0.65  # 0.7 * 0.5 + 0.3 * 1
    assert next_mastery(0.5, 0.0) == 0.35
    assert next_mastery(None, 1.0) == 0.65  # a new concept starts in the middle
    assert next_mastery(1.0, 1.0) == 1.0


@pytest.mark.parametrize(
    ("value", "level"),
    [(None, "not_started"), (0.39, "weak"), (0.40, "improving"), (0.64, "improving"),
     (0.65, "strong"), (0.84, "strong"), (0.85, "mastered")],
)  # fmt: skip
def test_mastery_levels(value, level):
    assert mastery_level(value) == level


def test_mistake_types():
    misconception = uuid.uuid4()
    assert mcq_mistake_type(misconception, 0.9) == MistakeType.MISCONCEPTION
    assert mcq_mistake_type(None, 0.9) == MistakeType.CARELESS
    assert mcq_mistake_type(None, 0.5) == MistakeType.KNOWLEDGE_GAP
    assert mcq_mistake_type(None, None) == MistakeType.KNOWLEDGE_GAP


def _row() -> QuizRow:
    topic = uuid.uuid4()
    return QuizRow(uuid.uuid4(), uuid.uuid4(), topic, "T", "stem", "medium", None)


def test_pick_prefers_unseen_then_weakest():
    rows = [_row() for _ in range(6)]
    seen = {rows[0].id, rows[1].id}
    picked = pick_questions(rows, 4, seen=seen, rng=random.Random(1))
    assert not {q.id for q in picked} & seen

    weakness = {r.id: 0.9 for r in rows}
    weakness[rows[5].id] = 0.1
    first = pick_questions(rows, 1, seen=set(), weakness=weakness, rng=random.Random(1))
    assert first[0].id == rows[5].id


def test_timed_quiz_minutes():
    assert (quiz_minutes(10), quiz_minutes(1), quiz_minutes(50)) == (15, 2, 75)


async def test_quizzes_require_login(anon_client):
    response = await anon_client.post("/api/v1/quizzes", json={})
    assert response.status_code == 401


# --------------------------------------------------------------------------- database fixtures


@pytest.fixture
async def bank(db_session, student_in_db):
    """Unit 91 with one topic, one concept and a misconception; 4 approved MCQs (option C of
    each is mapped to the misconception), plus a draft and an outdated one."""
    unit = Unit(number=91, title="Quiz unit")
    db_session.add(unit)
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="91.1", title="Membrane transport", code="bio-91.1")
    db_session.add(topic)
    await db_session.flush()
    concept = Concept(topic_id=topic.id, name="Active transport")
    db_session.add(concept)
    await db_session.flush()
    misconception = Misconception(
        concept_id=concept.id,
        title="Confuses active transport with facilitated diffusion",
        correction_md="Active transport needs ATP; facilitated diffusion does not.",
    )
    db_session.add(misconception)
    await db_session.flush()
    question_ids = []
    specs = [(ContentStatus.APPROVED, False)] * 4 + [
        (ContentStatus.DRAFT, False),
        (ContentStatus.APPROVED, True),
    ]
    for i, (status, outdated) in enumerate(specs):
        q = Question(
            topic_id=topic.id,
            unit_id=unit.id,
            question_type=QuestionType.MCQ,
            stem=f"Q{i} {'HIDDEN' if outdated or status != ContentStatus.APPROVED else 'ok'}",
            explanation="Because ATP is used.",
            status=status,
            is_outdated=outdated,
        )
        db_session.add(q)
        await db_session.flush()
        question_ids.append(q.id)
        db_session.add(QuestionConcept(question_id=q.id, concept_id=concept.id))
        for label in "ABCDE":
            db_session.add(
                MCQOption(
                    question_id=q.id,
                    label=label,
                    text=f"opt {label}",
                    is_correct=label == "B",
                    misconception_id=misconception.id if label == "C" else None,
                )
            )
    await db_session.commit()
    yield {"unit": unit.id, "topic": topic.id, "concept": concept.id, "misc": misconception.id}
    await db_session.execute(delete(Mistake).where(Mistake.user_id == STUDENT.id))
    await db_session.execute(delete(Question).where(Question.id.in_(question_ids)))
    await db_session.execute(delete(Misconception).where(Misconception.id == misconception.id))
    await db_session.execute(delete(Unit).where(Unit.id == unit.id))
    await db_session.commit()


def option(question: dict, letter: str) -> str:
    return next(o["id"] for o in question["options"] if o["label"] == letter)


# --------------------------------------------------------------------------- the loop


@pytest.mark.db
async def test_start_hides_answers_and_skips_unapproved(bank):
    async with make_api_client(user=STUDENT) as c:
        response = await c.post("/api/v1/quizzes", json={"topic": "bio-91.1", "count": 10})
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["total"], body["answered"], body["status"]) == (4, 0, "in_progress")
    assert all("HIDDEN" not in q["stem"] for q in body["questions"])
    assert all(q["correct_option_id"] is None for q in body["questions"])
    assert [o["label"] for o in body["questions"][0]["options"]] == list("ABCDE")
    assert body["timed"] is False and body["time_limit_minutes"] is None


@pytest.mark.db
async def test_wrong_answer_gives_misconception_mistake_and_mastery(bank, db_session):
    async with make_api_client(user=STUDENT) as c:
        quiz = (await c.post("/api/v1/quizzes", json={"unit": "91", "timed": True})).json()
        q = quiz["questions"][0]
        url = f"/api/v1/quizzes/{quiz['quiz_id']}/responses"
        wrong = await c.post(url, json={"question_id": q["id"], "option_id": option(q, "C")})
        again = await c.post(url, json={"question_id": q["id"], "option_id": option(q, "B")})
    assert quiz["time_limit_minutes"] == 6
    assert wrong.status_code == 200, wrong.text
    fb = wrong.json()
    assert fb["is_correct"] is False
    assert fb["correct_option_id"] == option(q, "B")
    assert fb["misconception"]["title"].startswith("Confuses active transport")
    assert fb["concept"]["name"] == "Active transport"
    assert fb["mastery"] == {"before": None, "after": 35, "level": "weak"}
    assert fb["mistake_type"] == "misconception"
    assert (fb["answered"], fb["total"]) == (1, 4)
    assert again.json()["error"]["code"] == "ALREADY_ANSWERED"

    mistakes = (
        (await db_session.execute(select(Mistake).where(Mistake.user_id == STUDENT.id)))
        .scalars()
        .all()
    )
    assert len(mistakes) == 1
    assert mistakes[0].misconception_id == bank["misc"]
    assert mistakes[0].concept_id == bank["concept"]
    mastery = (
        await db_session.execute(select(ConceptMastery).where(ConceptMastery.user_id == STUDENT.id))
    ).scalar_one()
    assert mastery.mastery_score == pytest.approx(0.35)


@pytest.mark.db
async def test_third_same_misconception_is_recurring(bank):
    async with make_api_client(user=STUDENT) as c:
        quiz = (await c.post("/api/v1/quizzes", json={"topic": str(bank["topic"])})).json()
        url = f"/api/v1/quizzes/{quiz['quiz_id']}/responses"
        feedback = [
            (await c.post(url, json={"question_id": q["id"], "option_id": option(q, "C")})).json()
            for q in quiz["questions"][:3]
        ]
        recurring = (await c.get("/api/v1/mistakes/recurring")).json()
    assert [f["recurring_misconception"] for f in feedback] == [False, False, True]
    assert feedback[2]["recurring_count"] == 3
    assert recurring["items"][0]["count"] == 3
    assert recurring["items"][0]["concept"] == "Active transport"


@pytest.mark.db
async def test_submit_result_and_unit_snapshot(bank, db_session):
    async with make_api_client(user=STUDENT) as c:
        quiz = (await c.post("/api/v1/quizzes", json={"unit": "u91"})).json()
        base = f"/api/v1/quizzes/{quiz['quiz_id']}"
        early = await c.get(f"{base}/result")
        q1, q2 = quiz["questions"][:2]
        await c.post(
            f"{base}/responses", json={"question_id": q1["id"], "option_id": option(q1, "B")}
        )
        await c.post(
            f"{base}/responses", json={"question_id": q2["id"], "option_id": option(q2, "A")}
        )
        flagged = await c.patch(f"{base}/questions/{q1['id']}/flag", json={"flagged": True})
        result = await c.post(f"{base}/submit")
        twice = await c.post(f"{base}/submit")
        stored = await c.get(f"{base}/result")
        resumed = (await c.get(base)).json()
        late = await c.post(
            f"{base}/responses", json={"question_id": q1["id"], "option_id": option(q1, "B")}
        )
        hub = (await c.get("/api/v1/practice/hub")).json()
    assert early.json()["error"]["code"] == "QUIZ_NOT_FINISHED"
    assert flagged.status_code == 204
    assert result.status_code == 200, result.text
    body = result.json()
    assert (body["score"], body["total"], body["answered"], body["percent"]) == (1, 4, 2, 25)
    assert body["mistakes"] == 1
    assert body["by_topic"][0]["topic"] == "Membrane transport"
    assert body["review"][0]["flagged"] is True and body["review"][0]["is_correct"] is True
    assert body["review"][2]["selected"] is None
    assert twice.json() == body and stored.json() == body
    assert resumed["status"] == "graded"
    assert resumed["questions"][2]["correct_option_id"] is not None  # solutions after submitting
    assert late.json()["error"]["code"] == "QUIZ_FINISHED"
    assert hub["in_progress"] is None and hub["recent"][0]["percent"] == 25

    snapshots = (
        await db_session.execute(
            select(func.count()).select_from(UnitMastery).where(UnitMastery.user_id == STUDENT.id)
        )
    ).scalar_one()
    assert snapshots == 1
    # only the two answered questions touched the concept: 0.5 -> 0.65 -> 0.455
    mastery = (
        await db_session.execute(
            select(ConceptMastery.mastery_score).where(ConceptMastery.user_id == STUDENT.id)
        )
    ).scalar_one()
    assert mastery == pytest.approx(0.455)


@pytest.mark.db
async def test_mistakes_only_and_errors(bank):
    async with make_api_client(user=STUDENT) as c:
        none_yet = await c.post("/api/v1/quizzes", json={"mistakes_only": True})
        no_unit = await c.post("/api/v1/quizzes", json={"unit": "999"})
        hard = await c.post("/api/v1/quizzes", json={"unit": "91", "difficulty": "hard"})
        quiz = (await c.post("/api/v1/quizzes", json={"unit": "91"})).json()
        q = quiz["questions"][0]
        await c.post(
            f"/api/v1/quizzes/{quiz['quiz_id']}/responses",
            json={"question_id": q["id"], "option_id": option(q, "D")},
        )
        retry = await c.post("/api/v1/quizzes", json={"mistakes_only": True})
        other = await c.get(f"/api/v1/quizzes/{uuid.uuid4()}")
    assert none_yet.json()["error"]["code"] == "NO_MISTAKES"
    assert no_unit.json()["error"]["code"] == "UNIT_NOT_FOUND"
    assert hard.json()["error"]["code"] == "NO_QUESTIONS"
    assert retry.status_code == 201
    assert [x["id"] for x in retry.json()["questions"]] == [q["id"]]
    assert other.json()["error"]["code"] == "QUIZ_NOT_FOUND"


@pytest.mark.db
async def test_overview_and_heatmap(bank):
    async with make_api_client(user=STUDENT) as c:
        quiz = (await c.post("/api/v1/quizzes", json={"unit": "91"})).json()
        q = quiz["questions"][0]
        await c.post(
            f"/api/v1/quizzes/{quiz['quiz_id']}/responses",
            json={"question_id": q["id"], "option_id": option(q, "B"), "time_spent_seconds": 120},
        )
        await c.post(f"/api/v1/quizzes/{quiz['quiz_id']}/submit")
        overview = (await c.get("/api/v1/insights/overview")).json()
        heatmap = (await c.get("/api/v1/insights/heatmap")).json()
    assert overview["study_minutes_week"] == 2
    assert len(overview["study_time"]) == 7
    assert overview["accuracy_trend"][-1]["accuracy"] is not None
    assert overview["overall_mastery"] is not None
    unit = next(u for u in heatmap["units"] if u["number"] == 91)
    assert unit["topics"][0]["mastery"] == 65 and unit["topics"][0]["level"] == "strong"


# --------------------------------------------------------------------------- question quality


def test_statistics_send_suspicious_questions_to_review():
    from api.modules.quality.service import needs_review

    assert needs_review(29, 1.0) is False  # too few answers to judge
    assert needs_review(30, 0.96) is True and needs_review(30, 0.09) is True
    assert needs_review(30, 0.95) is False and needs_review(200, 0.5) is False


@pytest.mark.db
async def test_answers_are_counted_and_reports_work(bank, db_session):
    from shared.db.models import QuestionStats

    async with make_api_client(user=STUDENT) as c:
        quiz = (await c.post("/api/v1/quizzes", json={"unit": "91"})).json()
        q = quiz["questions"][0]
        await c.post(
            f"/api/v1/quizzes/{quiz['quiz_id']}/responses",
            json={"question_id": q["id"], "option_id": option(q, "C")},
        )
        reported = await c.post(
            f"/api/v1/questions/{q['id']}/report", json={"reason": "wrong_answer"}
        )
        twice = await c.post(f"/api/v1/questions/{q['id']}/report", json={"reason": "typo"})
        unknown = await c.post(f"/api/v1/questions/{uuid.uuid4()}/report", json={"reason": "typo"})
    stats = (
        await db_session.execute(
            select(QuestionStats).where(QuestionStats.question_id == uuid.UUID(q["id"]))
        )
    ).scalar_one()
    assert (stats.attempts_count, stats.correct_count, stats.option_counts) == (1, 0, {"C": 1})
    assert reported.status_code == 201 and reported.json()["sent_to_review"] is False
    assert twice.json()["error"]["code"] == "ALREADY_REPORTED"
    assert unknown.json()["error"]["code"] == "QUESTION_NOT_FOUND"
