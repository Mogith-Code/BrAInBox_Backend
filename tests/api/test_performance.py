"""Tests for the performance module: topic-wise MCQ scores, weak topics, feedback.
Owner: Keshomigha."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

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
