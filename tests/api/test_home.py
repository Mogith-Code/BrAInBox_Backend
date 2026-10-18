"""Home dashboard summary. Owner: Samni."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from api.core import clock
from api.core.config import get_settings
from api.core.security import CurrentUser
from api.modules.home.service import days_to_exam, greeting_name, initials
from api.modules.performance.service import count_streak
from api.modules.recommendations.service import FocusUnit, build_plan_items, minutes_scale
from shared.db.models import DailyPlanItem
from shared.enums import UserRole
from tests.api.test_diagnostic import FakeAI, answer_letter, question_bank  # noqa: F401
from tests.conftest import STUDENT, make_api_client

ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# --------------------------------------------------------------------------- pure logic


def person(full_name: str | None, email: str | None = "nethmi.p@gmail.com") -> CurrentUser:
    return CurrentUser(uuid.uuid4(), "uid", email, UserRole.STUDENT, full_name)


def test_greeting_and_initials():
    assert (greeting_name(person("Nethmi Perera")), initials(person("Nethmi Perera"))) == (
        "Nethmi",
        "NP",
    )
    assert (greeting_name(person("Nethmi")), initials(person("Nethmi"))) == ("Nethmi", "N")
    assert (greeting_name(person(None)), initials(person(None))) == ("nethmi.p", "N")
    assert greeting_name(person(None, email=None)) == "there"


def test_days_to_exam(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: date(2026, 10, 7))
    monkeypatch.setattr(get_settings(), "AL_EXAM_DATES", {2027: date(2027, 7, 21)})
    assert days_to_exam(2027) == 287
    assert days_to_exam(2028) is None  # date not configured yet
    assert days_to_exam(None) is None


def test_streak_counting():
    today = date(2026, 10, 7)
    days = {today - timedelta(days=i) for i in range(12)}
    assert count_streak(days, today) == 12
    assert count_streak(days - {today}, today) == 11  # not studied yet today: still counts
    assert count_streak({today - timedelta(days=2)}, today) == 0
    assert count_streak(set(), today) == 0


def test_plan_items_from_weak_units():
    unit = FocusUnit(uuid.uuid4(), 6, "Genetics", uuid.uuid4(), "Dihybrid crosses")
    items = build_plan_items(uuid.uuid4(), date(2026, 10, 7), [unit], hours_per_day=2)
    assert [i.title for i in items] == [
        "Recap: Dihybrid crosses",
        "Practice: 10 MCQs Dihybrid crosses",
        "Read short notes: Dihybrid crosses",
    ]
    assert [i.minutes for i in items] == [10, 15, 5]
    assert minutes_scale(4) == 2 and minutes_scale(0.5) == 1 and minutes_scale(None) == 1


# --------------------------------------------------------------------------- database


async def set_profile(c, study_days: list[str]) -> None:  # type: ignore[no-untyped-def]
    response = await c.patch(
        "/api/v1/profile",
        json={
            "stream": "bio_science",
            "subject": "biology",
            "exam_year": clock.today().year + 1,
            "target_grade": "A",
            "confidence": 50,
            "study_days": study_days,
            "hours_per_day": 2,
            "preferred_time": "evening",
        },
    )
    assert response.status_code == 200, response.text


async def take_diagnostic(c, weak_unit: str = "3") -> None:  # type: ignore[no-untyped-def]
    """Everything right except all questions of `weak_unit`."""
    start = (await c.post("/api/v1/diagnostic/start")).json()
    for q in start["questions"]:
        letter = "A" if q["unit_code"] == weak_unit else "B"
        await c.post(
            f"/api/v1/diagnostic/{start['attempt_id']}/answer",
            json={"question_id": q["id"], "option_id": answer_letter(q, letter)},
        )
    response = await c.post(f"/api/v1/diagnostic/{start['attempt_id']}/submit")
    assert response.status_code == 200, response.text


@pytest.mark.db
async def test_new_student_sees_the_diagnostic_first(student_in_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "AL_EXAM_DATES", {})
    async with make_api_client(user=STUDENT, ai=FakeAI()) as c:
        await set_profile(c, ALL_DAYS)
        summary = (await c.get("/api/v1/home/summary")).json()

    assert summary["greeting_name"] == "student"  # STUDENT has no full name, so the email name
    assert summary["streak_days"] == 0
    assert summary["days_to_exam"] is None  # exam date not configured
    action = summary["next_best_action"]
    assert (action["type"], action["button_label"], action["ai_generated"]) == (
        "diagnostic",
        "Start diagnostic",
        False,
    )
    assert summary["todays_plan"] == {"done": 0, "total": 0, "items": []}
    assert summary["overall_mastery"] is None
    assert summary["mastery_change_week"] == 0
    assert summary["continue_learning"] == []


@pytest.mark.db
async def test_after_diagnostic_weakest_unit_and_plan(question_bank, db_session, monkeypatch):  # noqa: F811
    exam_day = clock.today() + timedelta(days=287)
    monkeypatch.setattr(get_settings(), "AL_EXAM_DATES", {exam_day.year: exam_day})
    student = CurrentUser(
        STUDENT.id, STUDENT.firebase_uid, STUDENT.email, STUDENT.role, "Nethmi Perera"
    )
    async with make_api_client(user=student, ai=FakeAI()) as c:
        await set_profile(c, ALL_DAYS)
        await c.patch("/api/v1/profile", json={"exam_year": exam_day.year})
        await take_diagnostic(c, weak_unit="3")
        first = (await c.get("/api/v1/home/summary")).json()
        second = (await c.get("/api/v1/home/summary")).json()
        item_id = first["todays_plan"]["items"][0]["id"]
        ticked = await c.patch(f"/api/v1/home/plan/{item_id}", json={"done": True})
        third = (await c.get("/api/v1/home/summary")).json()
        missing = await c.patch(f"/api/v1/home/plan/{uuid.uuid4()}", json={"done": True})

    assert (first["greeting_name"], first["initials"]) == ("Nethmi", "NP")
    assert first["days_to_exam"] == 287
    assert first["streak_days"] == 1  # answering the diagnostic today counts as study
    action = first["next_best_action"]
    assert action["type"] == "revise"
    assert action["title"] == "Revise: Topic 3"
    assert action["target"]["unit_code"] == "3"
    assert action["reason"] == "AI reason: revise this unit first."  # from FakeAI
    assert action["ai_generated"] is True

    plan = first["todays_plan"]
    assert (plan["done"], plan["total"]) == (0, 3)
    assert plan["items"][0]["title"] == "Recap: Topic 3"
    assert plan["items"][0]["unit_label"] == "Unit 3"
    assert [i["id"] for i in second["todays_plan"]["items"]] == [i["id"] for i in plan["items"]]
    count = await db_session.execute(select(func.count()).select_from(DailyPlanItem))
    assert count.scalar_one() == 3  # created once per day

    assert ticked.json()["done"] is True
    assert (third["todays_plan"]["done"], third["todays_plan"]["total"]) == (1, 3)
    assert missing.json()["error"]["code"] == "PLAN_ITEM_NOT_FOUND"

    assert 0 < first["overall_mastery"] < 100
    assert first["mastery_change_week"] == 0  # no history older than 7 days yet
    assert first["continue_learning"][0] == {
        "topic_id": action["target"]["topic_id"],
        "title": "Topic 3",
        "unit_code": "3",
        "progress": 17,  # 0 of 2 right -> (0 + 0.5) / 3
    }
    assert len(first["continue_learning"]) == 5


@pytest.mark.db
async def test_next_action_falls_back_when_ai_fails(question_bank):  # noqa: F811
    async with make_api_client(user=STUDENT, ai=FakeAI(fail=True)) as c:
        await set_profile(c, ALL_DAYS)
        await take_diagnostic(c)
        action = (await c.get("/api/v1/home/summary")).json()["next_best_action"]
    assert action["type"] == "revise"
    assert action["ai_generated"] is False
    assert "Unit 3" in action["reason"]


@pytest.mark.db
async def test_no_plan_on_a_rest_day(question_bank):  # noqa: F811
    today = ALL_DAYS[clock.today().weekday()]
    async with make_api_client(user=STUDENT, ai=FakeAI()) as c:
        await set_profile(c, [d for d in ALL_DAYS if d != today])
        await take_diagnostic(c)
        plan = (await c.get("/api/v1/home/summary")).json()["todays_plan"]
    assert plan == {"done": 0, "total": 0, "items": []}


@pytest.mark.db
async def test_weekly_mastery_change(question_bank, db_session):  # noqa: F811
    """overall_mastery = average of the newest values; change = vs the newest values > 7 days old."""
    from shared.db.models import UnitMastery

    eight_days_ago = clock.now() - timedelta(days=8)
    for unit_id in question_bank:
        db_session.add(
            UnitMastery(user_id=STUDENT.id, unit_id=unit_id, mastery=40, created_at=eight_days_ago)
        )
        db_session.add(UnitMastery(user_id=STUDENT.id, unit_id=unit_id, mastery=50))
    await db_session.commit()
    async with make_api_client(user=STUDENT, ai=FakeAI()) as c:
        summary = (await c.get("/api/v1/home/summary")).json()
    assert summary["overall_mastery"] == 50
    assert summary["mastery_change_week"] == 10
