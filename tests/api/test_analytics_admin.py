"""Tests for admin analytics (/api/v1/admin/analytics). Owner: Keshomigha."""

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from api.core import clock
from api.modules.performance import repository, service
from api.modules.syllabus.schemas import UnitOut
from shared.db.models import (
    AIUsageLog,
    Attempt,
    MCQOption,
    Misconception,
    Paper,
    Question,
    Response,
    StudyActivity,
    Topic,
    Unit,
    UnitMastery,
    User,
)
from shared.enums import QuestionType, UserRole

BASE = "/api/v1/admin/analytics"
ENDPOINTS = ["/overview", "/performance", "/ai-usage"]

# --------------------------------------------------------------------------- pure rules


def test_period_includes_today():
    assert service.period_start(date(2026, 11, 7), 1) == date(2026, 11, 7)
    assert service.period_start(date(2026, 11, 7), 7) == date(2026, 11, 1)


def test_fill_days_has_no_gaps():
    days = service.fill_days({date(2026, 11, 2): 5}, date(2026, 11, 1), date(2026, 11, 3))
    assert [(d.day.day, d.count) for d in days] == [(1, 0), (2, 5), (3, 0)]


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [(120, 100, 20.0), (50, 100, -50.0), (5, 0, None), (0, 0, None), (1, 3, -66.7)],
)
def test_change_percent(current, previous, expected):
    assert service.change_percent(current, previous) == expected


def test_feature_usage_is_ranked_with_shares():
    usage = service.feature_usage({"notes": 1, "visuals": 3})
    assert [(u.feature, u.requests, u.percent) for u in usage] == [
        ("visuals", 3, 75.0),
        ("notes", 1, 25.0),
    ]
    assert service.feature_usage({}) == []


def test_unit_average_without_measurements_is_not_zero():
    units = [UnitOut(id=uuid.uuid4(), number=n, title=f"Unit {n}", topic_count=1) for n in (1, 2)]
    rows = service.build_unit_averages(units, {units[0].id: (61.26, 4)})
    assert (rows[0].average_mastery, rows[0].students_assessed) == (61.3, 4)
    assert (rows[1].average_mastery, rows[1].students_assessed) == (None, 0)


# --------------------------------------------------------------------------- access + validation


@pytest.mark.parametrize("path", ENDPOINTS)
async def test_students_cannot_see_analytics(client, path):
    response = await client.get(BASE + path)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("path", ENDPOINTS)
async def test_analytics_requires_login(anon_client, path):
    assert (await anon_client.get(BASE + path)).status_code == 401


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.parametrize("days", [0, 366, "abc"])
async def test_bad_period_is_rejected(admin_client, path, days):
    assert (await admin_client.get(f"{BASE}{path}?days={days}")).status_code == 422


# --------------------------------------------------------------------------- real database


DAY_ONLY_THIS_TEST_USES = 4000  # days ago: no other test or real student has activity then


def _uid() -> str:
    return f"analytics-{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def analytics_data(db_session):
    """Two students and an admin with known activity. Everything is removed afterwards.

    Topic A: 6 answers, 4 wrong (66.7 %). Topic B: 6 answers, 1 wrong. Topic C: 4 answers, all
    wrong, but too few to list. The admin's wrong answers in topic B must not count.
    """
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    today = clock.today()
    s1, s2 = (User(firebase_uid=_uid(), role=UserRole.STUDENT) for _ in range(2))
    admin = User(firebase_uid=_uid(), role=UserRole.ADMIN)
    unit = Unit(number=random.randint(100_000, 999_000), title=f"Analytics unit {tag}")
    db_session.add_all([s1, s2, admin, unit])
    await db_session.flush()
    topics = [
        Topic(unit_id=unit.id, number=f"A.{i}", title=f"Analytics topic {tag} {name}")
        for i, name in enumerate("ABC")
    ]
    misconception = Misconception(title=f"Analytics misconception {tag}")
    db_session.add_all([*topics, misconception])
    await db_session.flush()
    paper = Paper(title=f"Analytics paper {tag}")
    db_session.add(paper)
    await db_session.flush()

    attempts = {
        user.id: Attempt(
            paper_id=paper.id, user_id=user.id, status="graded", submitted_at=now, score=0
        )
        for user in (s1, s2, admin)
    }
    old = Attempt(
        paper_id=paper.id,
        user_id=s1.id,
        status="graded",
        submitted_at=now - timedelta(days=60),
        score=0,
    )
    unfinished = Attempt(paper_id=paper.id, user_id=s2.id, status="in_progress")
    db_session.add_all([*attempts.values(), old, unfinished])
    await db_session.flush()

    async def answers(attempt, topic, correct, wrong, misconception_id=None):
        for is_correct, count in ((True, correct), (False, wrong)):
            for _ in range(count):
                question = Question(
                    topic_id=topic.id,
                    question_type=QuestionType.MCQ,
                    stem=f"Analytics question {tag}",
                )
                db_session.add(question)
                await db_session.flush()
                option = MCQOption(
                    question_id=question.id,
                    label="A",
                    text="x",
                    is_correct=is_correct,
                    misconception_id=None if is_correct else misconception_id,
                )
                db_session.add(option)
                await db_session.flush()
                db_session.add(
                    Response(
                        attempt_id=attempt.id,
                        question_id=question.id,
                        selected_option_id=option.id,
                        is_correct=is_correct,
                    )
                )

    await answers(attempts[s1.id], topics[0], correct=1, wrong=2, misconception_id=misconception.id)
    await answers(attempts[s2.id], topics[0], correct=1, wrong=2, misconception_id=misconception.id)
    await answers(attempts[s1.id], topics[1], correct=5, wrong=1)
    await answers(attempts[s2.id], topics[2], correct=0, wrong=4)
    await answers(attempts[admin.id], topics[1], correct=0, wrong=50)  # an admin: not counted
    await answers(old, topics[1], correct=0, wrong=50)  # 60 days ago: only in long periods
    await answers(unfinished, topics[1], correct=0, wrong=50)  # not finished: never counted

    db_session.add_all(
        [
            StudyActivity(user_id=s1.id, activity_date=today),
            StudyActivity(user_id=s2.id, activity_date=today),
            StudyActivity(user_id=s2.id, activity_date=today - timedelta(days=1)),
            StudyActivity(user_id=s1.id, activity_date=today - timedelta(days=8)),
            StudyActivity(user_id=admin.id, activity_date=today),
            StudyActivity(
                user_id=s1.id, activity_date=today - timedelta(days=DAY_ONLY_THIS_TEST_USES)
            ),
            StudyActivity(
                user_id=admin.id, activity_date=today - timedelta(days=DAY_ONLY_THIS_TEST_USES)
            ),
            # student 1's older mastery must be replaced by the newer one
            UnitMastery(
                user_id=s1.id,
                unit_id=unit.id,
                mastery=10,
                source="diagnostic",
                created_at=now - timedelta(days=9),
            ),
            UnitMastery(user_id=s1.id, unit_id=unit.id, mastery=80, source="exam"),
            UnitMastery(user_id=s2.id, unit_id=unit.id, mastery=60, source="diagnostic"),
            UnitMastery(user_id=admin.id, unit_id=unit.id, mastery=1, source="diagnostic"),
        ]
    )
    feature = f"analytics{tag}"
    db_session.add_all(
        [
            AIUsageLog(
                provider="gemini",
                operation="generate",
                prompt_name=f"{feature}/x.v1",
            ),
            AIUsageLog(
                provider="gemini",
                operation="generate",
                prompt_name=f"{feature}/y.v1",
            ),
            AIUsageLog(
                provider="gemini",
                operation="generate",
                prompt_name=f"{feature}/old.v1",
                created_at=now - timedelta(days=60),
            ),
        ]
    )
    await db_session.commit()
    yield SimpleNamespace(unit=unit, topics=topics, misconception=misconception, feature=feature)
    await db_session.execute(delete(AIUsageLog).where(AIUsageLog.prompt_name.like(f"{feature}/%")))
    await db_session.execute(delete(Paper).where(Paper.id == paper.id))
    await db_session.execute(delete(Question).where(Question.stem == f"Analytics question {tag}"))
    await db_session.execute(delete(Misconception).where(Misconception.id == misconception.id))
    await db_session.execute(delete(User).where(User.id.in_([s1.id, s2.id, admin.id])))
    await db_session.execute(delete(Unit).where(Unit.id == unit.id))
    await db_session.commit()


@pytest.mark.db
async def test_active_students_leave_out_admins(analytics_data, db_session):
    """A quiet day long ago: one student and one admin studied, so exactly one is counted."""
    day = clock.today() - timedelta(days=DAY_ONLY_THIS_TEST_USES)
    assert await repository.count_active_students(db_session, day, day) == 1
    assert (await repository.daily_active_students(db_session, day))[day] == 1


@pytest.mark.db
async def test_overview_totals(admin_client, analytics_data):
    """Other rows may exist in the database, so totals are checked as minimums here; the exact
    numbers are checked on this test's own topics, unit and misconception below."""
    body = (await admin_client.get(f"{BASE}/overview?days=7")).json()
    assert body["days"] == 7
    assert body["since"] == str(clock.today() - timedelta(days=6))
    assert len(body["daily_active_students"]) == 7
    assert body["daily_active_students"][-1]["day"] == str(clock.today())
    assert body["total_students"] >= 2
    assert body["new_students"] >= 2
    assert body["active_students"] >= 2
    assert body["active_students_previous"] >= 1  # student 1, 8 days ago
    assert body["attempts_completed"] >= 2
    assert body["mcq_answers"] >= 16  # 6 + 6 + 4 from the two students' recent attempts
    today_count = body["daily_active_students"][-1]["count"]
    assert today_count >= 2


@pytest.mark.db
async def test_performance_lists_real_results(admin_client, analytics_data):
    body = (await admin_client.get(f"{BASE}/performance?days=30")).json()
    topics = {t["topic_id"]: t for t in body["most_missed_topics"]}
    a, b, c = (str(t.id) for t in analytics_data.topics)

    assert (topics[a]["answers"], topics[a]["wrong"], topics[a]["wrong_percent"]) == (6, 4, 66.7)
    # The admin's, the 60-day-old and the unfinished attempt's 150 wrong answers don't count.
    assert (topics[b]["answers"], topics[b]["wrong"]) == (6, 1)
    assert c not in topics  # only 4 answers: too few to list
    assert body["min_answers_per_topic"] == 5
    ranked = [t["topic_id"] for t in body["most_missed_topics"]]
    assert ranked.index(a) < ranked.index(b)

    mine = next(
        m
        for m in body["misconceptions"]
        if m["misconception_id"] == str(analytics_data.misconception.id)
    )
    assert (mine["times_chosen"], mine["students"]) == (4, 2)

    unit = next(u for u in body["units"] if u["unit_id"] == str(analytics_data.unit.id))
    assert (unit["average_mastery"], unit["students_assessed"]) == (70.0, 2)  # (80 + 60) / 2


@pytest.mark.db
async def test_performance_longer_period_includes_older_answers(admin_client, analytics_data):
    body = (await admin_client.get(f"{BASE}/performance?days=90")).json()
    b = next(
        t for t in body["most_missed_topics"] if t["topic_id"] == str(analytics_data.topics[1].id)
    )
    assert (b["answers"], b["wrong"]) == (56, 51)


@pytest.mark.db
async def test_ai_usage_counts_requests_and_does_not_invent_a_cost(admin_client, analytics_data):
    body = (await admin_client.get(f"{BASE}/ai-usage?days=30")).json()
    mine = next(f for f in body["by_feature"] if f["feature"] == analytics_data.feature)
    assert mine["requests"] == 2  # the 60-day-old call is outside the period
    assert body["total_requests"] >= 2
    assert len(body["daily_requests"]) == 30
    assert body["daily_requests"][-1]["count"] >= 2


async def test_ai_cost_is_null_when_not_recorded(admin_client, monkeypatch):
    """The AI service doesn't log cost or tokens yet: that must not look like $0."""

    async def totals(session, since):
        return SimpleNamespace(
            requests=3, images=1, cost_usd=None, input_tokens=None, output_tokens=None
        )

    async def by_feature(session, since):
        return {"notes": 3}

    async def daily(session, since):
        return {}

    monkeypatch.setattr(repository, "ai_usage_totals", totals)
    monkeypatch.setattr(repository, "ai_usage_by_feature", by_feature)
    monkeypatch.setattr(repository, "daily_ai_requests", daily)
    response = await admin_client.get(f"{BASE}/ai-usage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["days"] == 30  # the default period
    assert (body["total_requests"], body["images"]) == (3, 1)
    assert body["total_cost_usd"] is None
    assert body["input_tokens"] is None and body["output_tokens"] is None


@pytest.mark.db
async def test_recorded_ai_cost_and_tokens_are_added_up(admin_client, db_session):
    feature = f"cost{uuid.uuid4().hex[:8]}"
    db_session.add(
        AIUsageLog(
            provider="gemini",
            operation="generate",
            prompt_name=f"{feature}/x.v1",
            cost_usd=0.25,
            input_tokens=100,
            output_tokens=40,
        )
    )
    await db_session.commit()
    try:
        body = (await admin_client.get(f"{BASE}/ai-usage?days=1")).json()
        assert body["total_cost_usd"] >= 0.25
        assert body["input_tokens"] >= 100
        assert body["output_tokens"] >= 40
    finally:
        await db_session.execute(
            delete(AIUsageLog).where(AIUsageLog.prompt_name.like(f"{feature}/%"))
        )
        await db_session.commit()
