"""Recommendations and the weekly study plan (rule-based, explainable)."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from api.modules.performance.service import ConceptState
from api.modules.recommendations import youtube_client
from api.modules.recommendations.service import (
    build_suggestions,
    fit_plan,
    priority_band,
    priority_score,
    recency_weight,
    suggestions_for,
)
from shared.db.models import (
    Concept,
    ConceptMastery,
    MCQOption,
    Misconception,
    Mistake,
    Question,
    QuestionConcept,
    Recommendation,
    Resource,
    Topic,
    Unit,
)
from shared.enums import ContentStatus, MistakeType, QuestionType, RecommendationAction
from tests.conftest import STUDENT, make_api_client

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def state(**changes) -> ConceptState:  # type: ignore[no-untyped-def]
    base = {
        "concept_id": uuid.uuid4(),
        "name": "Active transport",
        "topic_id": uuid.uuid4(),
        "topic_title": "Cell membrane",
        "topic_code": "bio-2.3",
        "unit_id": uuid.uuid4(),
        "unit_number": 2,
        "unit_title": "Cells",
        "exam_weight": 1.0,
        "mastery": 0.5,
        "attempts": 3,
        "last_practiced_at": NOW - timedelta(days=1),
    }
    return ConceptState(**{**base, **changes})


# --------------------------------------------------------------------------- pure rules


def test_priority_formula():
    assert recency_weight(NOW - timedelta(days=2), NOW) == 1.0
    assert recency_weight(NOW - timedelta(days=20), NOW) == 0.8
    assert recency_weight(NOW - timedelta(days=90), NOW) == 0.6
    assert priority_score(state(mastery=0.2), NOW) == 0.8
    assert priority_score(state(mastery=0.2, exam_weight=2.0), NOW) == 1.6
    assert priority_score(state(mastery=0.2, recurring_count=3), NOW) == pytest.approx(1.2)
    assert (
        priority_score(state(mastery=0.2, last_practiced_at=NOW - timedelta(days=20)), NOW) == 0.64
    )


def test_weak_concept_gets_notes_then_a_quiz():
    out = suggestions_for(state(mastery=0.3, open_mistakes=3), NOW)
    assert [s.action for s in out] == [
        RecommendationAction.REVISE_NOTE,
        RecommendationAction.PRACTICE_QUIZ,
    ]
    assert out[0].reason.startswith("Because you missed 3 questions on")
    assert out[1].target["count"] == 10 and out[0].score > out[1].score


def test_recurring_misconception_gets_five_targeted_questions():
    out = suggestions_for(
        state(mastery=0.5, recurring_count=3, recurring_misconception="Mixes up X and Y",
              recurring_misconception_id=uuid.uuid4()),
        NOW,
    )  # fmt: skip
    assert len(out) == 1
    assert out[0].target["kind"] == "misconception" and out[0].target["count"] == 5
    assert "3 times in the last 14 days" in out[0].reason


def test_improving_written_and_reassess_rules():
    improving = suggestions_for(state(mastery=0.5), NOW)
    assert [s.target["kind"] for s in improving] == ["targeted"]
    written = suggestions_for(state(mastery=0.7, written_mistakes=2), NOW)
    assert [s.action for s in written] == [RecommendationAction.RETRY_ANSWER]
    stale = suggestions_for(state(mastery=0.9, last_practiced_at=NOW - timedelta(days=10)), NOW)
    assert [s.action for s in stale] == [RecommendationAction.REASSESS]
    assert suggestions_for(state(mastery=0.9), NOW) == []  # strong and fresh: nothing to do


def test_suggestions_are_sorted_by_priority():
    weak, ok = state(mastery=0.1, name="Weak"), state(mastery=0.6, name="Ok")
    out = build_suggestions([ok, weak], NOW)
    assert "Weak" in out[0].title and "Ok" in out[-1].title
    assert [priority_band(i, 10) for i in (0, 1, 2, 9)] == [1, 1, 2, 5]


def rec(
    minutes_count: int | None = None, action=RecommendationAction.REVISE_NOTE
) -> Recommendation:
    return Recommendation(
        id=uuid.uuid4(),
        action_type=action,
        target_ref={"count": minutes_count} if minutes_count else {},
    )


def test_plan_fits_study_days_and_minutes():
    recs = [rec() for _ in range(5)]  # 15 minutes each
    monday = date(2026, 11, 16)
    slots = fit_plan(recs, start=monday, study_days=["mon", "wed"], minutes_per_day=30)
    assert [(s.day.isoformat(), s.order) for s in slots] == [
        ("2026-11-16", 0), ("2026-11-16", 1), ("2026-11-18", 0), ("2026-11-18", 1),
    ]  # fmt: skip
    # no study days chosen = every day; an item longer than the day still gets its own day
    long = [rec(40, RecommendationAction.PRACTICE_QUIZ), rec()]
    slots = fit_plan(long, start=monday, study_days=[], minutes_per_day=30)
    assert [(s.day.day, s.minutes) for s in slots] == [(16, 60), (17, 15)]
    # at most 4 items a day
    many = fit_plan([rec() for _ in range(6)], start=monday, study_days=[], minutes_per_day=600)
    assert [s.day.day for s in many] == [16, 16, 16, 16, 17, 17]


def test_youtube_durations():
    assert youtube_client.parse_duration("PT12M30S") == 750
    assert youtube_client.parse_duration("PT1H2M") == 3720
    assert youtube_client.parse_duration("P0D") is None
    assert youtube_client.right_length(180) and youtube_client.right_length(1500)
    assert not youtube_client.right_length(179) and not youtube_client.right_length(1501)


async def test_recommendations_require_login(anon_client):
    assert (await anon_client.get("/api/v1/recommendations")).status_code == 401


# --------------------------------------------------------------------------- with the database


class RankAI:
    async def sync(self, name, payload):  # type: ignore[no-untyped-def]
        assert name == "rank-resources"
        return {"result": {"resources": [{"id": payload["candidates"][0]["id"], "score": 0.8}]}}


async def _wipe(session) -> None:  # type: ignore[no-untyped-def]
    await session.rollback()
    await session.execute(delete(Mistake).where(Mistake.user_id == STUDENT.id))
    topics = select(Topic.id).join(Unit, Unit.id == Topic.unit_id).where(Unit.number == 93)
    await session.execute(delete(Resource).where(Resource.topic_id.in_(topics)))
    await session.execute(delete(Question).where(Question.topic_id.in_(topics)))
    concepts = select(Concept.id).where(Concept.topic_id.in_(topics))
    await session.execute(delete(Misconception).where(Misconception.concept_id.in_(concepts)))
    await session.execute(delete(Unit).where(Unit.number == 93))
    await session.commit()


@pytest.fixture
async def learner(db_session, student_in_db):
    """A student who is weak at one concept (with 3 mistakes) and stale at a strong one."""
    await _wipe(db_session)
    unit = Unit(number=93, title="Recommendation unit", exam_weight=1.0)
    db_session.add(unit)
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="93.1", title="Membranes", code="bio-93.1")
    db_session.add(topic)
    await db_session.flush()
    weak = Concept(topic_id=topic.id, name="Active transport")
    strong = Concept(topic_id=topic.id, name="Osmosis", order_index=1)
    db_session.add_all([weak, strong])
    await db_session.flush()
    question = Question(
        topic_id=topic.id, question_type=QuestionType.MCQ, stem="Q", status=ContentStatus.APPROVED
    )
    db_session.add(question)
    await db_session.flush()
    db_session.add(QuestionConcept(question_id=question.id, concept_id=weak.id))
    for label in "ABCDE":
        db_session.add(
            MCQOption(question_id=question.id, label=label, text=label, is_correct=label == "A")
        )
    now = datetime.now(UTC)
    db_session.add_all(
        [
            ConceptMastery(user_id=STUDENT.id, concept_id=weak.id, mastery_score=0.2,
                           attempts_count=4, last_practiced_at=now),
            ConceptMastery(user_id=STUDENT.id, concept_id=strong.id, mastery_score=0.9,
                           attempts_count=6, last_practiced_at=now - timedelta(days=12)),
        ]
    )  # fmt: skip
    db_session.add_all(
        [
            Mistake(user_id=STUDENT.id, question_id=question.id, concept_id=weak.id,
                    mistake_type=MistakeType.KNOWLEDGE_GAP)
            for _ in range(3)
        ]
    )  # fmt: skip
    await db_session.commit()
    yield {"weak": weak.id, "strong": strong.id, "topic": topic.id}
    await _wipe(db_session)


@pytest.mark.db
async def test_new_student_gets_a_hint_not_made_up_steps(student_in_db):
    async with make_api_client(user=STUDENT) as c:
        recs = (await c.get("/api/v1/recommendations")).json()
        plan = (await c.get("/api/v1/study-plan")).json()
    assert recs["items"] == [] and "diagnostic" in recs["hint"]
    assert plan["total"] == 0 and plan["hint"]


@pytest.mark.db
async def test_recommendations_explain_themselves_and_survive_refresh(learner):
    async with make_api_client(user=STUDENT) as c:
        first = (await c.get("/api/v1/recommendations")).json()["items"]
        again = (await c.get("/api/v1/recommendations")).json()["items"]
        dismissed = await c.patch(
            f"/api/v1/recommendations/{first[0]['id']}", json={"status": "dismissed"}
        )
        after = (await c.get("/api/v1/recommendations")).json()["items"]
        outcome = (await c.get(f"/api/v1/recommendations/{first[1]['id']}/outcome")).json()
        missing = await c.get(f"/api/v1/recommendations/{uuid.uuid4()}/outcome")
    assert [r["action"] for r in first] == ["revise_note", "practice_quiz", "reassess"]
    assert first[0]["reason"].startswith("Because you missed 3 questions on “Active transport”")
    assert first[0]["priority"] == 1 and first[0]["mastery"] == 20
    assert first[1]["target"]["count"] == 10 and first[1]["estimated_minutes"] == 15
    assert first[2]["concept"] == "Osmosis" and "12 days ago" in first[2]["reason"]
    assert [r["id"] for r in again] == [r["id"] for r in first]  # stable ids across refreshes
    assert dismissed.json()["status"] == "dismissed"
    assert first[0]["id"] not in [r["id"] for r in after] and len(after) == 2
    assert outcome["before"] == 20 and outcome["after"] == 20 and outcome["improved"] is False
    assert missing.json()["error"]["code"] == "RECOMMENDATION_NOT_FOUND"


@pytest.mark.db
async def test_videos_are_fetched_ranked_and_cached(learner, monkeypatch, db_session):
    calls = []

    async def fake_search(query, max_results=10):  # type: ignore[no-untyped-def]
        calls.append(query)
        return [
            {"video_id": "vid1", "title": "Active transport", "description": "", "channel": "Bio",
             "thumbnail_url": None, "duration_seconds": 600},
            {"video_id": "vid2", "title": "Unrelated", "description": "", "channel": "X",
             "thumbnail_url": None, "duration_seconds": 600},
        ]  # fmt: skip

    monkeypatch.setattr(youtube_client, "search_videos", fake_search)
    async with make_api_client(user=STUDENT, ai=RankAI()) as c:
        first = (await c.get("/api/v1/recommendations")).json()["items"]
        (await c.get("/api/v1/recommendations")).json()
    videos = [r for r in first if r["action"] == "watch_video"]
    assert calls == ["A/L Biology Active transport"]  # the second request used the cache
    assert len(videos) == 1 and videos[0]["resource"]["url"].endswith("v=vid1")
    assert videos[0]["resource"]["duration_seconds"] == 600
    stored = (
        (
            await db_session.execute(
                select(Resource.external_id).where(Resource.provider == "youtube")
            )
        )
        .scalars()
        .all()
    )
    assert "vid1" in stored and "vid2" not in stored  # the weak match was dropped


@pytest.mark.db
async def test_study_plan_generate_tick_and_reorder(learner):
    async with make_api_client(user=STUDENT) as c:
        plan = (await c.get("/api/v1/study-plan")).json()
        same = (await c.get("/api/v1/study-plan")).json()
        day = next(d for d in plan["days"] if d["items"])
        ids = [i["id"] for i in day["items"]]
        ticked = await c.patch(f"/api/v1/study-plan/items/{ids[0]}", json={"is_done": True})
        reordered = await c.put("/api/v1/study-plan/order", json={"item_ids": ids[::-1]})
        bad = await c.put("/api/v1/study-plan/order", json={"item_ids": [str(uuid.uuid4())]})
        recs = (await c.get("/api/v1/recommendations")).json()["items"]
        new = (await c.post("/api/v1/study-plan/regenerate")).json()
    assert plan["total"] == 3 and len(plan["days"]) == 7 and plan["done"] == 0
    assert same["id"] == plan["id"]
    assert day["minutes_planned"] == 40 and day["minutes_available"] == 60
    assert ticked.json()["is_done"] is True
    new_day = next(d for d in reordered.json()["days"] if d["items"])
    assert [i["id"] for i in new_day["items"]] == ids[::-1]
    assert reordered.json()["done"] == 1
    assert bad.json()["error"]["code"] == "PLAN_ORDER_INVALID"
    assert len(recs) == 2  # the ticked item completed its recommendation
    assert new["id"] != plan["id"] and new["total"] == 2
