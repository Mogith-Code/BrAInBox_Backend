"""Profile page (GET /profile/overview), achievements, Settings > Notifications (GET/PATCH
/settings) and Data & privacy (GET/PATCH /privacy). Owner: Mogith (profiles)."""

import dataclasses
import random
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select

from api.core import clock
from api.core.config import get_settings
from api.core.security import CurrentUser
from api.modules.performance import service as performance_service
from api.modules.performance.service import weak_to_strong
from api.modules.profiles import service as profiles_service
from shared.db.models import (
    Attempt,
    MCQOption,
    Paper,
    PaperQuestion,
    Question,
    Response,
    StudentProfile,
    StudyActivity,
    Topic,
    Unit,
    UnitMastery,
    User,
    UserAchievement,
    UserSettings,
    UserTopicProgress,
)
from shared.enums import ContentStatus, TopicProgressStatus, UserRole
from tests.api.test_exams import TAG, FakeAIClient, _app_with, _bank_question
from tests.conftest import STUDENT, _client, make_api_client

NAMED = dataclasses.replace(STUDENT, full_name="Nethmi Perera")
OTHER = CurrentUser(
    id=uuid.UUID(int=78), firebase_uid="profile-other", email=None, role=UserRole.STUDENT
)
ICONS = {"streak", "first_mastery", "unit_fixer", "mcq_100", "past_paper_pro", "unit_master"}
ACHIEVEMENT_KEYS = {
    "id", "title", "icon", "description", "unlocked", "unlocked_at", "seen", "badge_label", "xp"
}  # fmt: skip


# --------------------------------------------------------------------------- no DB


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/profile/overview"),
        ("post", "/api/v1/achievements/streak_7/seen"),
        ("get", "/api/v1/settings"),
        ("patch", "/api/v1/settings"),
        ("get", "/api/v1/privacy"),
        ("patch", "/api/v1/privacy"),
    ],
)
async def test_endpoints_need_login(anon_client, method, path):
    response = await anon_client.request(method, path, json={} if method == "patch" else None)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"reminder_time": "25:00"},
        {"reminder_time": "8:30"},
        {"reminder_time": "20:30:00"},
        {"reminder_time": "20:60"},
        {"reminder_time": "half past eight"},
        {"reminder_time": None},
        {"study_reminders": None},
        {"study_reminders": "yes"},
        {"community_replies": 1},
    ],
)
async def test_settings_validation(client, body):
    response = await client.patch("/api/v1/settings", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "body",
    [{"improve_ai": None}, {"share_research": "no"}, {"show_name_in_community": 0}],
)
async def test_privacy_validation(client, body):
    response = await client.patch("/api/v1/privacy", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_weak_to_strong():
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    history = [
        (a, 30), (a, 80),  # weak -> strong: yes
        (b, 80),  # strong from the start: no
        (c, 30), (c, 80), (c, 50),  # strong, then weak again: no
        (d, 60), (d, 90),  # developing -> strong (never weak): no
    ]  # fmt: skip
    assert weak_to_strong(history) == [a]


def test_days_to_exam(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: date(2026, 10, 7))
    monkeypatch.setattr(get_settings(), "AL_EXAM_DATES", {2027: date(2027, 7, 21)})
    assert profiles_service.days_to_exam(2027) == 287
    assert profiles_service.days_to_exam(2028) is None
    assert profiles_service.days_to_exam(None) is None


# --------------------------------------------------------------------------- DB fixtures


@pytest.fixture
async def other_in_db(db_session, student_in_db):
    await db_session.execute(delete(User).where(User.id == OTHER.id))  # left by a crashed run
    db_session.add(User(id=OTHER.id, firebase_uid=OTHER.firebase_uid, role=UserRole.STUDENT))
    await db_session.commit()
    yield OTHER.id
    await db_session.execute(delete(User).where(User.id == OTHER.id))
    await db_session.commit()


@pytest.fixture
async def unit_with_topics(db_session):
    """A unit with two topics (removed afterwards)."""
    unit = Unit(number=random.randint(1000, 999_999), title="Genetics test unit")
    db_session.add(unit)
    await db_session.flush()
    unit_id = unit.id  # rows expire after a rollback (MissingGreenlet)
    topics = [Topic(unit_id=unit.id, number=f"G.{n}", title=f"Gene topic {n}") for n in (1, 2)]
    db_session.add_all(topics)
    await db_session.commit()
    yield unit, topics
    await db_session.execute(delete(Unit).where(Unit.id == unit_id))
    await db_session.commit()


async def _unlocked(db_session, user_id) -> dict[str, UserAchievement]:
    db_session.expire_all()
    rows = await db_session.scalars(
        select(UserAchievement).where(UserAchievement.user_id == user_id)
    )
    return {r.achievement_id: r for r in rows}


# --------------------------------------------------------------------------- overview


@pytest.mark.db
async def test_overview_of_a_new_student(student_in_db):
    async with make_api_client(user=NAMED) as c:
        response = await c.get("/api/v1/profile/overview")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "full_name", "stream_label", "exam_year", "target_grade", "days_to_exam", "streak_days",
        "questions_answered", "topics_mastered", "achievements", "achievements_total",
    }  # fmt: skip
    assert body["full_name"] == "Nethmi Perera"
    assert (body["stream_label"], body["exam_year"], body["target_grade"]) == ("", None, None)
    assert body["days_to_exam"] is None
    assert (body["streak_days"], body["questions_answered"], body["topics_mastered"]) == (0, 0, 0)
    assert body["achievements_total"] == len(body["achievements"]) == 6
    for a in body["achievements"]:  # locked ones are listed too
        assert set(a) == ACHIEVEMENT_KEYS
        assert (a["unlocked"], a["unlocked_at"], a["seen"]) == (False, None, False)
        assert a["icon"] in ICONS and a["xp"] > 0
    assert {a["icon"] for a in body["achievements"]} == ICONS


@pytest.mark.db
async def test_overview_uses_real_data(student_in_db, db_session, unit_with_topics, monkeypatch):
    unit, topics = unit_with_topics
    today = clock.today()
    monkeypatch.setattr(get_settings(), "AL_EXAM_DATES", {2027: today + timedelta(days=40)})
    db_session.add(
        StudentProfile(user_id=STUDENT.id, stream="bio_science", exam_year=2027, target_grade="A")
    )
    db_session.add_all(
        StudyActivity(user_id=STUDENT.id, activity_date=today - timedelta(days=n)) for n in range(3)
    )
    db_session.add(
        UserTopicProgress(user_id=STUDENT.id, topic_id=topics[0].id,
                          status=TopicProgressStatus.MASTERED, score=90)
    )  # fmt: skip
    await db_session.commit()

    async with make_api_client(user=NAMED) as c:
        body = (await c.get("/api/v1/profile/overview")).json()

    assert body["stream_label"] == "Biological Science"
    assert (body["exam_year"], body["target_grade"], body["days_to_exam"]) == (2027, "A", 40)
    assert (body["streak_days"], body["topics_mastered"]) == (3, 1)


@pytest.mark.db
async def test_questions_answered_counts_my_answers(student_in_db, db_session, other_in_db):
    """MCQs with an option chosen and written answers with text, in my attempts only."""
    unit = Unit(number=random.randint(1000, 999_999), title="Count unit")
    db_session.add(unit)
    await db_session.flush()
    unit_id = unit.id  # rows expire after a rollback (MissingGreenlet)
    topic = Topic(unit_id=unit.id, number="C.1", title="Count topic")
    db_session.add(topic)
    await db_session.commit()
    try:
        mcq1 = await _bank_question(db_session, topic)
        mcq2 = await _bank_question(db_session, topic)
        paper = Paper(title=f"{TAG} count", paper_type="quiz")
        db_session.add(paper)
        await db_session.flush()
        mine = Attempt(paper_id=paper.id, user_id=STUDENT.id, status="graded")
        theirs = Attempt(paper_id=paper.id, user_id=OTHER.id, status="graded")
        db_session.add_all([mine, theirs])
        await db_session.flush()
        option_id = await db_session.scalar(
            select(MCQOption.id).where(MCQOption.question_id == mcq1.id).limit(1)
        )
        db_session.add_all(
            [
                Response(attempt_id=mine.id, question_id=mcq1.id, selected_option_id=option_id),
                Response(attempt_id=mine.id, question_id=mcq2.id),  # skipped: not counted
                Response(attempt_id=theirs.id, question_id=mcq1.id, selected_option_id=option_id),
            ]
        )
        await db_session.commit()
        answered = await performance_service.count_answers(db_session, STUDENT.id)
        mcqs = await performance_service.count_answers(db_session, STUDENT.id, mcq_only=True)
        assert (answered, mcqs) == (1, 1)
    finally:
        await db_session.rollback()
        await db_session.execute(delete(Paper).where(Paper.title.like(f"{TAG}%")))
        await db_session.execute(delete(Question).where(Question.unit_id == unit_id))
        await db_session.execute(delete(Unit).where(Unit.id == unit_id))
        await db_session.commit()


# --------------------------------------------------------------------------- achievements


@pytest.mark.db
async def test_unlock_and_seen_flow_through_a_past_paper(student_in_db, db_session, other_in_db):
    """Submitting a past paper on the 7th study day in a row unlocks "Past paper pro" and the
    7-day streak; the app then marks them seen. Only my own unlocks can be marked."""
    unit = Unit(number=random.randint(1000, 999_999), title="Paper unit")
    db_session.add(unit)
    await db_session.flush()
    unit_id = unit.id  # rows expire after a rollback (MissingGreenlet)
    topic = Topic(unit_id=unit.id, number="P.1", title="Paper topic")
    db_session.add(topic)
    today = clock.today()
    db_session.add_all(
        StudyActivity(user_id=STUDENT.id, activity_date=today - timedelta(days=n))
        for n in range(1, 7)
    )
    await db_session.commit()
    try:
        question = await _bank_question(db_session, topic)
        paper = Paper(title=f"{TAG} past", paper_type="past_paper", year=2024,
                      status=ContentStatus.APPROVED)  # fmt: skip
        db_session.add(paper)
        await db_session.flush()
        db_session.add(PaperQuestion(paper_id=paper.id, question_id=question.id, position=1))
        await db_session.commit()

        async with make_api_client(user=STUDENT) as c:
            before = (await c.get("/api/v1/profile/overview")).json()
        assert not any(a["unlocked"] for a in before["achievements"])

        async with _client(_app_with(FakeAIClient())) as c:
            submitted = await c.post(
                f"/api/v1/papers/{paper.id}/submit",
                json={"answers": [{"question_id": str(question.id), "selected": "B"}],
                      "explain": False},
            )  # fmt: skip
        assert submitted.status_code == 200, submitted.text
        assert set(await _unlocked(db_session, STUDENT.id)) == {"past_paper_pro", "streak_7"}

        async with make_api_client(user=STUDENT) as c:
            after = (await c.get("/api/v1/profile/overview")).json()
            seen = await c.post("/api/v1/achievements/past_paper_pro/seen")
            again = await c.post("/api/v1/achievements/past_paper_pro/seen")
            locked = await c.post("/api/v1/achievements/unit_master/seen")
            unknown = await c.post("/api/v1/achievements/no_such_badge/seen")
            final = (await c.get("/api/v1/profile/overview")).json()
        async with make_api_client(user=OTHER) as c:
            not_mine = await c.post("/api/v1/achievements/streak_7/seen")
            other_view = (await c.get("/api/v1/profile/overview")).json()
    finally:
        await db_session.rollback()
        await db_session.execute(delete(Paper).where(Paper.title.like(f"{TAG}%")))
        await db_session.execute(delete(Question).where(Question.unit_id == unit_id))
        await db_session.execute(delete(Unit).where(Unit.id == unit_id))
        await db_session.commit()

    # unlocked first, both unseen (the app shows the pop-up), then the locked ones
    first_two = after["achievements"][:2]
    assert {a["id"] for a in first_two} == {"past_paper_pro", "streak_7"}
    assert all(a["unlocked"] and not a["seen"] and a["unlocked_at"] for a in first_two)
    streak = next(a for a in first_two if a["id"] == "streak_7")
    assert streak["description"] == "You studied 7 days in a row."
    assert after["streak_days"] == 7 and after["questions_answered"] == 1
    assert not any(a["unlocked"] for a in after["achievements"][2:])

    assert (seen.status_code, seen.content) == (204, b"")
    assert again.status_code == 204  # safe to repeat
    for response in (locked, unknown, not_mine):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ACHIEVEMENT_NOT_FOUND"
    by_id = {a["id"]: a for a in final["achievements"]}
    assert (by_id["past_paper_pro"]["seen"], by_id["streak_7"]["seen"]) == (True, False)
    assert not any(a["unlocked"] for a in other_view["achievements"])  # mine stay mine


@pytest.mark.db
async def test_mastery_achievements(student_in_db, db_session, unit_with_topics):
    """First topic mastered, a unit from Weak to Strong, a whole unit mastered."""
    unit, topics = unit_with_topics
    one = UserTopicProgress(user_id=STUDENT.id, topic_id=topics[0].id,
                            status=TopicProgressStatus.MASTERED, score=90)  # fmt: skip
    db_session.add(one)
    db_session.add(UnitMastery(user_id=STUDENT.id, unit_id=unit.id, mastery=30, source="quiz"))
    await db_session.commit()
    assert await profiles_service.check_achievements(db_session, STUDENT.id) == ["first_mastery"]
    await db_session.commit()

    db_session.add(
        UserTopicProgress(user_id=STUDENT.id, topic_id=topics[1].id,
                          status=TopicProgressStatus.MASTERED, score=95)
    )  # fmt: skip
    await db_session.flush()
    db_session.add(UnitMastery(user_id=STUDENT.id, unit_id=unit.id, mastery=85, source="quiz"))
    await db_session.commit()
    added = await profiles_service.check_achievements(db_session, STUDENT.id)
    await db_session.commit()
    assert set(added) == {"unit_fixer", "unit_master"}

    unlocked = await _unlocked(db_session, STUDENT.id)
    assert unlocked["unit_fixer"].detail == "You took Genetics test unit from Weak to Strong."
    assert unlocked["unit_master"].detail == "You mastered every topic in Genetics test unit."
    # nothing new the second time
    assert await profiles_service.check_achievements(db_session, STUDENT.id) == []


@pytest.mark.db
async def test_mcq_100(student_in_db, db_session, monkeypatch):
    calls: list[bool] = []

    async def count(session, user_id, *, mcq_only=False):  # type: ignore[no-untyped-def]
        calls.append(mcq_only)
        return 99 if len(calls) == 1 else 100

    monkeypatch.setattr(performance_service, "count_answers", count)
    only = profiles_service.ACTIVITY_ACHIEVEMENTS
    assert await profiles_service.check_achievements(db_session, STUDENT.id, only=only) == []
    assert await profiles_service.check_achievements(db_session, STUDENT.id, only=only) == [
        "mcq_100"
    ]
    await db_session.commit()
    assert calls == [True, True]


# --------------------------------------------------------------------------- settings / privacy


@pytest.mark.db
async def test_settings_defaults_and_partial_patch(student_in_db, other_in_db):
    async with make_api_client(user=STUDENT) as c:
        defaults = (await c.get("/api/v1/settings")).json()
        time_only = (await c.patch("/api/v1/settings", json={"reminder_time": "06:05"})).json()
        flag_only = (await c.patch("/api/v1/settings", json={"study_reminders": False})).json()
        empty = (await c.patch("/api/v1/settings", json={})).json()
        read_back = (await c.get("/api/v1/settings")).json()
    async with make_api_client(user=OTHER) as c:
        theirs = (await c.get("/api/v1/settings")).json()

    assert defaults == {
        "study_reminders": True,
        "reminder_time": "20:30",
        "community_replies": True,
    }
    assert time_only == {
        "study_reminders": True,
        "reminder_time": "06:05",
        "community_replies": True,
    }
    assert flag_only == {
        "study_reminders": False,
        "reminder_time": "06:05",
        "community_replies": True,
    }
    assert empty == read_back == flag_only
    assert theirs == defaults  # my changes are mine only


@pytest.mark.db
async def test_privacy_defaults_and_partial_patch(student_in_db, other_in_db, db_session):
    async with make_api_client(user=STUDENT) as c:
        defaults = (await c.get("/api/v1/privacy")).json()
        changed = (
            await c.patch(
                "/api/v1/privacy",
                json={"share_research": True, "personalised_recommendations": False},
            )
        ).json()
        hidden = (await c.patch("/api/v1/privacy", json={"show_name_in_community": False})).json()
        read_back = (await c.get("/api/v1/privacy")).json()
        settings = (await c.get("/api/v1/settings")).json()
    async with make_api_client(user=OTHER) as c:
        theirs = (await c.get("/api/v1/privacy")).json()

    assert defaults == {
        "personalised_recommendations": True,
        "improve_ai": True,
        "show_name_in_community": True,
        "share_research": False,
    }
    assert changed == {**defaults, "share_research": True}  # personalised stays on
    assert hidden == read_back == {**changed, "show_name_in_community": False}
    assert settings["reminder_time"] == "20:30"  # one row for both, nothing else changed
    assert theirs == defaults
    rows = (await db_session.scalars(select(UserSettings.user_id))).all()
    assert STUDENT.id in rows and OTHER.id not in rows  # GET never creates a row
