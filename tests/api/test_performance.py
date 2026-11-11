"""Tests for the performance module: topic-wise MCQ scores, weak topics, feedback.
Owner: Keshomigha."""

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from api.core import clock
from api.modules.exams.service import GradingQuestion, evaluate_paper
from api.modules.performance import repository, service
from api.modules.performance.grading import (
    MIN_QUESTIONS_FOR_RELIABLE_RESULT,
    TopicStatus,
    grade_for,
    is_weak_percent,
)
from api.modules.performance.repository import AnswerRow
from api.modules.performance.schemas import MisconceptionOut, ResourceOut
from api.modules.syllabus import service as syllabus_service
from api.modules.syllabus.schemas import UnitOut
from shared.db.models import (
    Attempt,
    MCQOption,
    Paper,
    Question,
    Response,
    Topic,
    Unit,
    UnitMastery,
    User,
    UserTopicProgress,
)
from shared.enums import AttemptKind, QuestionType, TopicProgressStatus, UserRole
from tests.api.test_exams import FakeAIClient, _app_with, exam_data  # noqa: F401 (fixture)
from tests.conftest import STUDENT, _client

# --------------------------------------------------------------------------- placeholders


async def test_performance_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/performance/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_performance_status_placeholder(client):
    response = await client.get("/api/v1/performance/status")
    assert response.status_code == 200
    assert response.json() == {"module": "performance", "status": "todo"}


# --------------------------------------------------------------------------- grade bands


@pytest.mark.parametrize(
    ("percent", "grade", "status"),
    [
        (0, "F", TopicStatus.VERY_WEAK),
        (34.99, "F", TopicStatus.VERY_WEAK),
        (35, "S", TopicStatus.WEAK),
        (54.99, "S", TopicStatus.WEAK),
        (55, "C", TopicStatus.DEVELOPING),
        (64.99, "C", TopicStatus.DEVELOPING),
        (65, "B", TopicStatus.GOOD),
        (74.99, "B", TopicStatus.GOOD),
        (75, "A", TopicStatus.STRONG),
        (100, "A", TopicStatus.STRONG),
    ],
)
def test_grade_boundaries(percent, grade, status):
    band = grade_for(percent)
    assert (band.grade, band.status) == (grade, status)


def test_weak_means_grade_s_or_f():
    assert is_weak_percent(54.99)
    assert is_weak_percent(0)
    assert not is_weak_percent(55)


def test_grade_bands_out_lists_every_band_with_bounds():
    bands = [(b.grade, b.min_percent, b.max_percent) for b in service.grade_bands_out()]
    assert bands == [
        ("A", 75.0, None),
        ("B", 65.0, 75.0),
        ("C", 55.0, 65.0),
        ("S", 35.0, 55.0),
        ("F", 0.0, 35.0),
    ]


# --------------------------------------------------------------------------- scoring (no DB)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
GENETICS = uuid.uuid4()
CELLS = uuid.uuid4()
PHYSIOLOGY = uuid.uuid4()
TITLES = {GENETICS: "Genetics", CELLS: "Cell Biology", PHYSIOLOGY: "Human Physiology"}


class Rows:
    """Builds AnswerRow objects in time order, like the repository returns them."""

    def __init__(self) -> None:
        self.rows: list[AnswerRow] = []
        self.attempt = uuid.uuid4()

    def add(
        self,
        topic_id: uuid.UUID | None,
        correct: bool | None,
        *,
        answered: bool = True,
        question_id: uuid.UUID | None = None,
        attempt_id: uuid.UUID | None = None,
        option_of_other_question: bool = False,
        misconception_id: uuid.UUID | None = None,
        explanation: str | None = None,
    ) -> AnswerRow:
        qid = question_id or uuid.uuid4()
        row = AnswerRow(
            response_id=uuid.uuid4(),
            attempt_id=attempt_id or self.attempt,
            question_id=qid,
            question=f"Question {len(self.rows) + 1}?",
            question_explanation=explanation,
            topic_id=topic_id,
            topic=TITLES.get(topic_id) if topic_id else None,
            topic_number=None,
            unit=None,
            selected_option_id=uuid.uuid4() if answered else None,
            option_question_id=(uuid.uuid4() if option_of_other_question else qid)
            if answered
            else None,
            misconception_id=misconception_id,
            is_correct=correct if answered else None,
            created_at=T0 + timedelta(seconds=len(self.rows)),
        )
        self.rows.append(row)
        return row

    def many(self, topic_id: uuid.UUID, correct: int, wrong: int) -> None:
        for _ in range(correct):
            self.add(topic_id, True)
        for _ in range(wrong):
            self.add(topic_id, False)


def by_topic(analysis):
    return {t.topic: t for t in analysis.topics}


def test_topic_scores_for_multiple_topics():
    rows = Rows()
    rows.many(GENETICS, correct=3, wrong=7)  # 30 %
    rows.many(PHYSIOLOGY, correct=6, wrong=4)  # 60 %
    rows.many(CELLS, correct=8, wrong=2)  # 80 %
    analysis = service.analyse_answers(rows.rows)
    topics = by_topic(analysis)

    genetics = topics["Genetics"]
    assert (genetics.correct, genetics.attempted, genetics.percent) == (3, 10, 30.0)
    assert (genetics.grade, genetics.status, genetics.reliable) == (
        "F",
        TopicStatus.VERY_WEAK,
        True,
    )
    assert (topics["Human Physiology"].percent, topics["Human Physiology"].grade) == (60.0, "C")
    assert (topics["Cell Biology"].percent, topics["Cell Biology"].grade) == (80.0, "A")

    # Ranked from the lowest to the highest score.
    assert [t.topic for t in analysis.topics] == ["Genetics", "Human Physiology", "Cell Biology"]
    # Overall is a separate result over every valid answer: 17 / 30.
    assert (analysis.overall.correct, analysis.overall.attempted) == (17, 30)
    assert (analysis.overall.percent, analysis.overall.grade) == (56.67, "C")
    assert analysis.attempts_analysed == 1


def test_unanswered_questions_are_not_counted_as_attempted():
    rows = Rows()
    rows.many(CELLS, correct=4, wrong=1)
    rows.add(CELLS, None, answered=False)
    rows.add(CELLS, None, answered=False)
    cells = by_topic(service.analyse_answers(rows.rows))["Cell Biology"]
    assert (cells.correct, cells.attempted, cells.unanswered, cells.percent) == (4, 5, 2, 80.0)


def test_topic_with_zero_attempted_questions_is_not_zero_percent():
    rows = Rows()
    rows.add(GENETICS, None, answered=False)
    rows.add(GENETICS, None, answered=False)
    analysis = service.analyse_answers(rows.rows)
    genetics = by_topic(analysis)["Genetics"]
    assert genetics.percent is None
    assert genetics.grade is None
    assert genetics.status == TopicStatus.NOT_ATTEMPTED
    assert analysis.overall.percent is None
    assert analysis.overall.grade is None


def test_no_answers_at_all():
    analysis = service.analyse_answers([])
    assert analysis.topics == []
    assert analysis.overall.attempted == 0
    assert analysis.overall.percent is None


def test_fewer_than_five_attempted_is_insufficient_data():
    rows = Rows()
    rows.many(GENETICS, correct=0, wrong=MIN_QUESTIONS_FOR_RELIABLE_RESULT - 1)  # 0 % on 4
    genetics = by_topic(service.analyse_answers(rows.rows))["Genetics"]
    assert genetics.percent == 0.0
    assert genetics.grade == "F"  # provisional, shown for information
    assert genetics.status == TopicStatus.INSUFFICIENT_DATA
    assert genetics.reliable is False


def test_exactly_five_attempted_is_reliable():
    rows = Rows()
    rows.many(GENETICS, correct=1, wrong=4)  # 20 % on 5
    genetics = by_topic(service.analyse_answers(rows.rows))["Genetics"]
    assert (genetics.status, genetics.reliable) == (TopicStatus.VERY_WEAK, True)


def test_invalid_answers_are_excluded():
    rows = Rows()
    rows.many(CELLS, correct=5, wrong=0)
    rows.add(CELLS, False, option_of_other_question=True)  # option of another question
    bad = rows.add(CELLS, True)
    bad.is_correct = None  # never marked
    analysis = service.analyse_answers(rows.rows)
    cells = by_topic(analysis)["Cell Biology"]
    assert (cells.correct, cells.attempted, cells.percent) == (5, 5, 100.0)
    assert analysis.overall.excluded == 2


def test_duplicate_submission_in_one_attempt_counts_once_using_the_latest():
    rows = Rows()
    rows.many(CELLS, correct=4, wrong=0)
    question = uuid.uuid4()
    rows.add(CELLS, True, question_id=question)  # first submission
    rows.add(CELLS, False, question_id=question)  # re-submitted: latest wins
    cells = by_topic(service.analyse_answers(rows.rows))["Cell Biology"]
    assert (cells.correct, cells.attempted, cells.percent) == (4, 5, 80.0)


def test_same_question_in_two_attempts_counts_twice():
    rows = Rows()
    question = uuid.uuid4()
    rows.add(CELLS, False, question_id=question)
    rows.add(CELLS, True, question_id=question, attempt_id=uuid.uuid4())  # a later attempt
    analysis = service.analyse_answers(rows.rows)
    assert by_topic(analysis)["Cell Biology"].attempted == 2
    assert analysis.attempts_analysed == 2


def test_questions_without_a_topic_are_grouped_as_general():
    rows = Rows()
    rows.add(None, True)
    general = by_topic(service.analyse_answers(rows.rows))["General"]
    assert general.topic_id is None
    assert general.attempted == 1


# --------------------------------------------------------------------------- feedback (no DB)


def test_feedback_uses_only_the_students_real_results():
    rows = Rows()
    misconception = MisconceptionOut(id=uuid.uuid4(), title="Genes are proteins")
    other_misconception = MisconceptionOut(id=uuid.uuid4(), title="Not chosen by the student")
    with_answer = rows.add(GENETICS, False, misconception_id=misconception.id)
    with_explanation = rows.add(GENETICS, False, explanation="DNA carries genes.")
    rows.many(GENETICS, correct=3, wrong=5)  # 3 / 10 = 30 %
    analysis = service.analyse_answers(rows.rows)
    genetics = by_topic(analysis)["Genetics"]
    resource = ResourceOut(
        id=uuid.uuid4(), title="Genetics basics", url="https://x.test/g", resource_type="note"
    )

    feedback = service.build_feedback(
        genetics,
        analysis.wrong_by_topic[GENETICS],
        model_answers={with_answer.question_id: "Approved model answer."},
        misconceptions={m.id: m for m in (misconception, other_misconception)},
        resources=[resource],
    )

    assert (feedback.correct, feedback.attempted, feedback.percent, feedback.grade) == (
        3,
        10,
        30.0,
        "F",
    )
    assert "3 of 10" in feedback.summary
    assert feedback.action.startswith("You need to strengthen your understanding of Genetics.")
    assert len(feedback.review_questions) == service.MAX_REVIEW_QUESTIONS  # 7 wrong, capped
    review = {r.question_id: r.model_answer for r in feedback.review_questions}
    assert review[with_answer.question_id] == "Approved model answer."
    assert review[with_explanation.question_id] == "DNA carries genes."
    assert feedback.misconceptions == [misconception]  # only the one the student chose
    assert feedback.resources == [resource]


@pytest.mark.parametrize(
    ("correct", "wrong", "status", "starts_with"),
    [
        (6, 4, TopicStatus.DEVELOPING, "You have a developing understanding of Cell Biology."),
        (8, 2, TopicStatus.STRONG, "Excellent performance in Cell Biology."),
        (2, 1, TopicStatus.INSUFFICIENT_DATA, "Practise at least 2 more MCQ(s) from Cell Biology"),
    ],
)
def test_feedback_message_per_status(correct, wrong, status, starts_with):
    rows = Rows()
    rows.many(CELLS, correct=correct, wrong=wrong)
    analysis = service.analyse_answers(rows.rows)
    cells = by_topic(analysis)["Cell Biology"]
    feedback = service.build_feedback(cells, analysis.wrong_by_topic[CELLS])
    assert feedback.status == status
    assert feedback.action.startswith(starts_with)
    assert feedback.misconceptions == []  # nothing is invented
    assert feedback.resources == []


def test_strong_topic_has_no_review_questions_when_nothing_was_wrong():
    rows = Rows()
    rows.many(CELLS, correct=5, wrong=0)
    analysis = service.analyse_answers(rows.rows)
    feedback = service.build_feedback(by_topic(analysis)["Cell Biology"], [])
    assert feedback.review_questions == []


# --------------------------------------------------------------------------- exams use the same rule


def test_exam_weak_topics_use_the_shared_thresholds():
    opts = ["W", "X", "Y", "Z"]
    q = lambda topic, n: [  # noqa: E731
        GradingQuestion(uuid.uuid4(), topic, "?", opts, "X") for _ in range(n)
    ]
    developing, weak = q("Developing", 5), q("Weak", 2)
    chosen = {x.id: "B" for x in developing[:3]} | {weak[0].id: "B"}  # 60 % and 50 %
    result = evaluate_paper(uuid.uuid4(), developing + weak, chosen)
    assert result.weak_topics == ["Weak"]  # 60 % is grade C, no longer weak


# --------------------------------------------------------------------------- API (repository faked)


@pytest.fixture
def fake_repository(monkeypatch):
    """Replace the database queries so the endpoint can run without PostgreSQL."""
    calls: dict[str, object] = {}
    rows = Rows()
    rows.many(GENETICS, correct=1, wrong=4)  # 20 % F
    rows.many(CELLS, correct=4, wrong=0)  # 4 questions: insufficient data
    other_user_attempt = uuid.uuid4()

    async def get_attempt(session, attempt_id):
        if attempt_id == rows.attempt:
            return SimpleNamespace(id=attempt_id, user_id=STUDENT.id)
        if attempt_id == other_user_attempt:
            return SimpleNamespace(id=attempt_id, user_id=uuid.uuid4())
        return None

    async def get_mcq_answer_rows(session, user_id, attempt_id=None):
        calls["user_id"], calls["attempt_id"] = user_id, attempt_id
        return rows.rows

    async def empty_list(session, *args):
        return []

    async def empty_dict(session, *args):
        return {}

    monkeypatch.setattr(repository, "get_attempt", get_attempt)
    monkeypatch.setattr(repository, "get_mcq_answer_rows", get_mcq_answer_rows)
    monkeypatch.setattr(repository, "get_misconceptions", empty_list)
    monkeypatch.setattr(repository, "get_model_answers", empty_dict)
    monkeypatch.setattr(repository, "get_topic_resources", empty_dict)
    return SimpleNamespace(calls=calls, own_attempt=rows.attempt, other_attempt=other_user_attempt)


async def test_topic_insights_requires_login(anon_client):
    response = await anon_client.get("/api/v1/insights/topics")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_topic_insights_for_the_logged_in_student(client, fake_repository):
    response = await client.get("/api/v1/insights/topics")
    assert response.status_code == 200, response.text
    body = response.json()

    assert fake_repository.calls["user_id"] == STUDENT.id  # only the student's own answers
    assert [t["topic"] for t in body["topics"]] == ["Genetics", "Cell Biology"]
    assert body["weak_topics"] == ["Genetics"]
    assert body["insufficient_data_topics"] == ["Cell Biology"]
    assert body["overall"] == {
        "correct": 5,
        "attempted": 9,
        "unanswered": 0,
        "excluded": 0,
        "percent": 55.56,
        "grade": "C",
        "grade_label": "Credit Pass",
    }
    assert body["min_questions_per_topic"] == 5
    assert body["feedback"][0]["topic"] == "Genetics"
    assert "not official examination grades" in body["note"]


async def test_topic_insights_for_one_own_attempt(client, fake_repository):
    attempt = fake_repository.own_attempt
    response = await client.get("/api/v1/insights/topics", params={"attempt_id": str(attempt)})
    assert response.status_code == 200
    assert response.json()["attempt_id"] == str(attempt)
    assert fake_repository.calls["attempt_id"] == attempt


async def test_topic_insights_of_another_students_attempt_is_forbidden(client, fake_repository):
    response = await client.get(
        "/api/v1/insights/topics", params={"attempt_id": str(fake_repository.other_attempt)}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert "user_id" not in fake_repository.calls  # nothing was read


async def test_topic_insights_unknown_attempt(client, fake_repository):
    response = await client.get("/api/v1/insights/topics", params={"attempt_id": str(uuid.uuid4())})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ATTEMPT_NOT_FOUND"


async def test_topic_insights_rejects_a_bad_attempt_id(client):
    response = await client.get("/api/v1/insights/topics", params={"attempt_id": "not-a-uuid"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------------------------- full flow (DB)


@pytest.mark.db
async def test_insights_after_submitting_a_paper(exam_data):  # noqa: F811 (fixture from test_exams)
    """Generate + submit a paper through exams, then read the topic insights."""
    async with _client(_app_with(FakeAIClient())) as c:
        paper = (
            await c.post(
                "/api/v1/papers/generate",
                json={"topic_ids": [str(exam_data.id)], "num_questions": 6},
            )
        ).json()
        q = paper["questions"]
        answers = [{"question_id": x["id"], "selected": "B"} for x in q[:2]]  # 2 correct
        answers += [{"question_id": x["id"], "selected": "A"} for x in q[2:5]]  # 3 wrong
        answers += [{"question_id": q[5]["id"], "selected": None}]  # 1 unanswered
        submitted = await c.post(
            f"/api/v1/papers/{paper['paper_id']}/submit",
            json={"answers": answers, "explain": False},
        )
        assert submitted.status_code == 200, submitted.text

        response = await c.get(
            "/api/v1/insights/topics", params={"attempt_id": submitted.json()["attempt_id"]}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    topic = body["topics"][0]
    assert (topic["topic"], topic["correct"], topic["attempted"], topic["unanswered"]) == (
        "Test topic",
        2,
        5,
        1,
    )
    assert (topic["percent"], topic["grade"], topic["status"]) == (40.0, "S", "weak")
    assert body["weak_topics"] == ["Test topic"]
    assert len(body["feedback"][0]["review_questions"]) == 3


# --------------------------------------------------------------------------- unit insights (no DB)

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def _units(*numbers: int) -> list[UnitOut]:
    return [
        UnitOut(id=uuid.uuid4(), number=n, title=f"Unit {n} title", topic_count=3) for n in numbers
    ]


def _snapshot(mastery: int, source: str = "diagnostic") -> SimpleNamespace:
    return SimpleNamespace(mastery=mastery, source=source, created_at=NOW)


def test_unit_insights_for_a_new_student():
    result = service.build_unit_insights(_units(1, 2), latest={}, week_ago={})
    assert [u.number for u in result.units] == [1, 2]
    assert all(u.mastery is None for u in result.units)  # not assessed, never 0 %
    assert all(u.status == TopicStatus.NOT_ATTEMPTED for u in result.units)
    assert result.assessed_units == 0 and result.total_units == 2
    assert result.average_mastery is None
    assert result.strongest is None and result.weakest is None


def test_unit_grades_use_the_shared_grade_bands():
    units = _units(1, 2, 3)
    latest = {units[0].id: _snapshot(75), units[1].id: _snapshot(54), units[2].id: _snapshot(20)}
    rows = service.build_unit_insights(units, latest, week_ago={}).units
    assert [(u.grade, u.status) for u in rows] == [
        ("A", TopicStatus.STRONG),
        ("S", TopicStatus.WEAK),
        ("F", TopicStatus.VERY_WEAK),
    ]
    assert rows[0].source == "diagnostic" and rows[0].measured_at == NOW


def test_weekly_change_compares_a_unit_only_with_itself():
    units = _units(1, 2)
    latest = {units[0].id: _snapshot(70, "exam"), units[1].id: _snapshot(40)}
    week_ago = {units[0].id: 55}  # unit 2 was first measured this week
    rows = service.build_unit_insights(units, latest, week_ago).units
    assert rows[0].change_week == 15
    assert rows[1].change_week is None


def test_average_strongest_and_weakest_skip_units_not_assessed():
    units = _units(1, 2, 3, 4)
    latest = {units[0].id: _snapshot(80), units[1].id: _snapshot(40), units[3].id: _snapshot(40)}
    result = service.build_unit_insights(units, latest, week_ago={})
    assert result.assessed_units == 3
    assert result.average_mastery == 53.3  # (80 + 40 + 40) / 3, unit 3 left out
    assert result.strongest.number == 1
    assert result.weakest.number == 2  # tie at 40: the lower unit number wins


def test_measurements_of_units_not_in_the_syllabus_are_ignored():
    units = _units(1)
    latest = {units[0].id: _snapshot(60), uuid.uuid4(): _snapshot(10)}  # e.g. an outdated unit
    result = service.build_unit_insights(units, latest, week_ago={})
    assert result.total_units == 1 and result.assessed_units == 1
    assert result.weakest.mastery == 60


# --------------------------------------------------------------------------- unit insights (API)


async def test_unit_insights_requires_login(anon_client):
    assert (await anon_client.get("/api/v1/insights/units")).status_code == 401


async def test_unit_insights_for_the_logged_in_student(client, monkeypatch):
    units = _units(1, 2)
    asked_for = []

    async def get_units(session):
        return units

    async def latest_rows(session, user_id):
        asked_for.append(user_id)
        return {units[1].id: _snapshot(62)}

    async def week_ago(session, user_id, before=None):
        return {}

    monkeypatch.setattr(syllabus_service, "get_units", get_units)
    monkeypatch.setattr(repository, "latest_unit_mastery_rows", latest_rows)
    monkeypatch.setattr(repository, "latest_unit_mastery", week_ago)

    response = await client.get("/api/v1/insights/units")
    assert response.status_code == 200, response.text
    body = response.json()
    assert asked_for == [STUDENT.id]  # only the student's own data
    assert [u["status"] for u in body["units"]] == ["not_attempted", "developing"]
    assert body["units"][1]["mastery"] == 62
    assert body["units"][1]["grade"] == "C"
    assert body["weakest"]["number"] == 2
    assert [b["grade"] for b in body["grade_bands"]] == ["A", "B", "C", "S", "F"]


# --------------------------------------------------------------------------- unit insights (DB)


@pytest.mark.db
async def test_unit_insights_from_the_database(client, student_in_db, db_session):
    unit = Unit(number=random.randint(100_000, 999_000), title="Mastery test unit")
    db_session.add(unit)
    await db_session.flush()
    now = datetime.now(UTC)
    db_session.add_all(
        [
            UnitMastery(
                user_id=STUDENT.id,
                unit_id=unit.id,
                mastery=40,
                source="diagnostic",
                created_at=now - timedelta(days=9),
            ),
            UnitMastery(
                user_id=STUDENT.id,
                unit_id=unit.id,
                mastery=65,
                source="exam",
                created_at=now - timedelta(hours=1),
            ),
        ]
    )
    await db_session.commit()
    try:
        body = (await client.get("/api/v1/insights/units")).json()
        mine = next(u for u in body["units"] if u["unit_id"] == str(unit.id))
        assert (mine["mastery"], mine["source"], mine["change_week"]) == (65, "exam", 25)
        assert (mine["grade"], mine["status"]) == ("B", "good")
    finally:
        await db_session.execute(delete(Unit).where(Unit.id == unit.id))
        await db_session.commit()


# --------------------------------------------------------------------------- summary (no DB)

TODAY = date(2026, 11, 6)


def _summary(units=None, latest=None, week_ago=None, rows=None, days=None):  # type: ignore[no-untyped-def]
    unit_insights = service.build_unit_insights(units or [], latest or {}, week_ago or {})
    return service.build_summary(
        unit_insights, service.analyse_answers(rows or []), days or set(), TODAY
    )


def test_summary_for_a_new_student():
    s = _summary(units=_units(1, 2))
    assert (s.overall_mastery, s.mastery_change_week) == (None, None)
    assert (s.units_assessed, s.total_units) == (0, 2)
    assert s.strongest_unit is None and s.weakest_unit is None
    assert (s.mcq.attempted, s.mcq.percent, s.mcq.grade) == (0, None, None)  # never 0 %
    assert s.attempts_completed == 0
    assert s.topics.model_dump() == dict.fromkeys(s.topics.model_dump(), 0)
    assert s.weak_topics == []
    assert (s.streak_days, s.study_days_last_7, s.last_study_date) == (0, 0, None)


def test_summary_mastery_matches_unit_insights():
    units = _units(1, 2, 3)
    latest = {units[0].id: _snapshot(70), units[1].id: _snapshot(40), units[2].id: _snapshot(31)}
    week_ago = {units[0].id: 50, units[1].id: 50}  # unit 3 is new this week
    s = _summary(units=units, latest=latest, week_ago=week_ago)
    assert s.overall_mastery == 47.0  # (70 + 40 + 31) / 3, as in /insights/units
    assert s.mastery_change_week == 5.0  # (+20 and -10) / 2: unit 3 has no change to count
    assert (s.strongest_unit.number, s.weakest_unit.number) == (1, 3)


def test_summary_mcq_score_and_topic_levels():
    rows = Rows()
    rows.many(GENETICS, correct=1, wrong=5)  # 16.7 % over 6: very weak (F), reliable
    rows.many(CELLS, correct=5, wrong=0)  # 100 %: strong (A)
    rows.many(PHYSIOLOGY, correct=2, wrong=0)  # only 2 answers: insufficient data
    s = _summary(rows=rows.rows)
    assert (s.mcq.correct, s.mcq.attempted) == (8, 13)
    assert s.attempts_completed == 1
    assert (s.topics.strong, s.topics.very_weak, s.topics.insufficient_data) == (1, 1, 1)
    assert s.weak_topics == ["Genetics"]  # insufficient-data topics are never "weak"


def test_summary_streak_and_study_days():
    days = {TODAY, TODAY - timedelta(days=1), TODAY - timedelta(days=3), TODAY - timedelta(days=10)}
    s = _summary(days=days)
    assert s.streak_days == 2  # today + yesterday; the gap two days ago ends it
    assert s.study_days_last_7 == 3  # today, yesterday, 3 days ago (10 days ago is too old)
    assert s.last_study_date == TODAY


def test_summary_streak_survives_until_the_student_studies_today():
    s = _summary(days={TODAY - timedelta(days=1), TODAY - timedelta(days=2)})
    assert s.streak_days == 2
    assert s.last_study_date == TODAY - timedelta(days=1)


# --------------------------------------------------------------------------- summary (API)


async def test_summary_requires_login(anon_client):
    assert (await anon_client.get("/api/v1/insights/summary")).status_code == 401


async def test_summary_for_the_logged_in_student(client, monkeypatch):
    units = _units(1, 2)
    rows = Rows()
    rows.many(CELLS, correct=4, wrong=1)
    asked_for = []

    async def get_units(session):
        return units

    async def latest_rows(session, user_id):
        asked_for.append(user_id)
        return {units[0].id: _snapshot(80)}

    async def no_week_ago(session, user_id, before=None):
        return {}

    async def answers(session, user_id, attempt_id=None):
        asked_for.append(user_id)
        return rows.rows

    async def study_days(session, user_id, since):
        asked_for.append(user_id)
        return {clock.today()}  # the app's Sri Lanka date, like the service uses

    monkeypatch.setattr(syllabus_service, "get_units", get_units)
    monkeypatch.setattr(repository, "latest_unit_mastery_rows", latest_rows)
    monkeypatch.setattr(repository, "latest_unit_mastery", no_week_ago)
    monkeypatch.setattr(repository, "get_mcq_answer_rows", answers)
    monkeypatch.setattr(repository, "study_days_since", study_days)

    response = await client.get("/api/v1/insights/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert asked_for == [STUDENT.id] * 3  # only the student's own data
    assert (body["overall_mastery"], body["units_assessed"], body["total_units"]) == (80.0, 1, 2)
    assert (body["mcq"]["correct"], body["mcq"]["attempted"], body["mcq"]["percent"]) == (
        4,
        5,
        80.0,
    )
    assert body["topics"]["strong"] == 1
    assert (body["streak_days"], body["study_days_last_7"]) == (1, 1)


# --------------------------------------------------------------------------- topic progress (no DB)


def _scored(topic_id: uuid.UUID | None, correct: int, attempted: int):  # type: ignore[no-untyped-def]
    tally = service.TopicTally(
        topic_id=topic_id,
        topic="T",
        topic_number=None,
        unit=None,
        correct=correct,
        attempted=attempted,
    )
    return service.topic_performance(tally)


@pytest.mark.parametrize(
    ("correct", "attempted", "status", "score", "is_weak"),
    [
        (5, 5, TopicProgressStatus.MASTERED, 100, False),
        (15, 20, TopicProgressStatus.MASTERED, 75, False),  # exactly the "A" boundary
        (14, 20, TopicProgressStatus.IN_PROGRESS, 70, False),
        (3, 5, TopicProgressStatus.IN_PROGRESS, 60, False),
        (1, 5, TopicProgressStatus.IN_PROGRESS, 20, True),
        (0, 5, TopicProgressStatus.IN_PROGRESS, 0, True),
        # Fewer than 5 answers: too little to call it mastered or weak, whatever the score.
        (4, 4, TopicProgressStatus.IN_PROGRESS, 100, False),
        (0, 4, TopicProgressStatus.IN_PROGRESS, 0, False),
    ],
)
def test_progress_values_from_topic_score(correct, attempted, status, score, is_weak):
    topic_id = uuid.uuid4()
    assert service.progress_values(STUDENT.id, _scored(topic_id, correct, attempted)) == {
        "user_id": STUDENT.id,
        "topic_id": topic_id,
        "status": status,
        "score": score,
        "is_weak": is_weak,
    }


def test_progress_is_not_saved_without_a_topic_or_valid_answers():
    assert service.progress_values(STUDENT.id, _scored(None, 5, 5)) is None  # e.g. unit papers
    assert service.progress_values(STUDENT.id, _scored(uuid.uuid4(), 0, 0)) is None


async def test_start_topic_requires_login(anon_client):
    response = await anon_client.post("/api/v1/topics/bio-1.1/start")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


# --------------------------------------------------------------------------- topic progress (DB)


async def _submit_paper(c, topic_id, selected: list[str | None]):  # type: ignore[no-untyped-def]
    """Generate a paper with one question per entry and submit these answers ("B" is correct)."""
    paper = (
        await c.post(
            "/api/v1/papers/generate",
            json={"topic_ids": [str(topic_id)], "num_questions": len(selected)},
        )
    ).json()
    answers = [
        {"question_id": q["id"], "selected": s}
        for q, s in zip(paper["questions"], selected, strict=True)
    ]
    submitted = await c.post(
        f"/api/v1/papers/{paper['paper_id']}/submit", json={"answers": answers, "explain": False}
    )
    assert submitted.status_code == 200, submitted.text


@pytest.mark.db
async def test_submitting_a_paper_updates_the_learn_screens(exam_data):  # noqa: F811
    async with _client(_app_with(FakeAIClient())) as c:
        before = (await c.get(f"/api/v1/topics/{exam_data.id}")).json()
        await _submit_paper(c, exam_data.id, ["B", "B", "A", "A", "A", None])
        weak = (await c.get(f"/api/v1/topics/{exam_data.id}")).json()
        # 6 more correct: 8 of 11 valid answers over both attempts.
        await _submit_paper(c, exam_data.id, ["B"] * 6)
        better = (await c.get(f"/api/v1/topics/{exam_data.id}")).json()
        insights = (await c.get("/api/v1/insights/topics")).json()

    assert (before["status"], before["progressPct"], before["isWeak"]) == ("not_started", 0, False)
    assert (weak["status"], weak["progressPct"], weak["isWeak"]) == ("in_progress", 40, True)
    assert (better["status"], better["progressPct"], better["isWeak"]) == ("in_progress", 73, False)
    assert insights["topics"][0]["percent"] == 72.73  # Learn and Insights use the same score


@pytest.mark.db
async def test_a_reliable_a_grade_masters_the_topic(exam_data):  # noqa: F811
    async with _client(_app_with(FakeAIClient())) as c:
        await _submit_paper(c, exam_data.id, ["B"] * 5)
        topic = (await c.get(f"/api/v1/topics/{exam_data.id}")).json()
    assert (topic["status"], topic["progressPct"], topic["isWeak"]) == ("mastered", 100, False)


@pytest.mark.db
async def test_unchanged_progress_keeps_its_updated_at(exam_data, db_session):  # noqa: F811
    async with _client(_app_with(FakeAIClient())) as c:
        await _submit_paper(c, exam_data.id, ["B"] * 5)
    query = select(UserTopicProgress.updated_at).where(UserTopicProgress.topic_id == exam_data.id)
    first = (await db_session.execute(query)).scalar_one()
    await db_session.commit()

    await service.refresh_topic_progress(db_session, STUDENT.id)
    await db_session.commit()

    assert (await db_session.execute(query)).scalar_one() == first


@pytest.mark.db
async def test_start_topic_then_opening_it_again(exam_data):  # noqa: F811
    async with _client(_app_with(FakeAIClient())) as c:
        first = await c.post(f"/api/v1/topics/{exam_data.id}/start")
        again = await c.post(f"/api/v1/topics/{exam_data.id}/start")
        topic = (await c.get(f"/api/v1/topics/{exam_data.id}")).json()
    assert first.status_code == 200, first.text
    assert first.json() == {
        "id": str(exam_data.id),  # this test topic has no public code
        "uuid": str(exam_data.id),
        "status": "in_progress",
        "progressPct": 0,
        "isWeak": False,
    }
    assert again.json() == first.json()
    assert topic["status"] == "in_progress"


@pytest.mark.db
async def test_start_topic_never_changes_a_score_or_mastered(exam_data):  # noqa: F811
    async with _client(_app_with(FakeAIClient())) as c:
        await _submit_paper(c, exam_data.id, ["B"] * 5)
        started = await c.post(f"/api/v1/topics/{exam_data.id}/start")
    assert (started.json()["status"], started.json()["progressPct"]) == ("mastered", 100)


@pytest.mark.db
async def test_start_unknown_topic(client):
    response = await client.post("/api/v1/topics/no-such-topic/start")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TOPIC_NOT_FOUND"


# --------------------------------------------------------------------------- which attempts count


@pytest.mark.db
async def test_which_attempts_count(db_session):
    """One answer in an attempt of each status and kind: marked attempts of every kind count
    (the diagnostic included), unfinished and abandoned ones never do."""
    user = User(firebase_uid=f"finished-{uuid.uuid4().hex[:12]}", role=UserRole.STUDENT)
    unit = Unit(number=random.randint(100_000, 999_000), title="Finished attempts unit")
    db_session.add_all([user, unit])
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="F.1", title="Finished attempts topic")
    paper = Paper(title="Finished attempts paper")
    db_session.add_all([topic, paper])
    await db_session.flush()

    cases = [
        ("graded", AttemptKind.EXAM, True),
        ("graded", AttemptKind.DIAGNOSTIC, True),
        ("submitted", AttemptKind.QUIZ, True),
        ("evaluated", AttemptKind.EXAM, True),
        ("in_progress", AttemptKind.EXAM, False),
        ("abandoned", AttemptKind.QUIZ, False),
    ]
    expected = set()
    for status, kind, counts in cases:
        attempt = Attempt(paper_id=paper.id, user_id=user.id, kind=kind, status=status)
        question = Question(
            topic_id=topic.id, question_type=QuestionType.MCQ, stem="Finished attempts question"
        )
        db_session.add_all([attempt, question])
        await db_session.flush()
        option = MCQOption(question_id=question.id, label="A", text="x", is_correct=False)
        db_session.add(option)
        await db_session.flush()
        db_session.add(
            Response(
                attempt_id=attempt.id,
                question_id=question.id,
                selected_option_id=option.id,
                is_correct=False,
            )
        )
        if counts:
            expected.add(attempt.id)
    await db_session.commit()
    try:
        rows = await repository.get_mcq_answer_rows(db_session, user.id)
        assert {r.attempt_id for r in rows} == expected
    finally:
        await db_session.execute(delete(Paper).where(Paper.id == paper.id))
        await db_session.execute(
            delete(Question).where(Question.stem == "Finished attempts question")
        )
        await db_session.execute(delete(User).where(User.id == user.id))
        await db_session.execute(delete(Unit).where(Unit.id == unit.id))
        await db_session.commit()
