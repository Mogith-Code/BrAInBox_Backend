"""Admin dashboard: GET /admin/dashboard. Owner: Samni."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete

from api.core import clock
from api.modules.admin.service import day_labels, percent_delta, report_card
from api.modules.community.schemas import ModerationItemOut
from shared.db.models import (
    Attempt,
    ContentReport,
    MCQOption,
    Misconception,
    Note,
    Paper,
    Post,
    Question,
    Response,
    StudentProfile,
    StudyActivity,
    Topic,
    Unit,
    User,
)
from shared.enums import ContentSource, ContentStatus, QuestionType, UserRole

URL = "/api/v1/admin/dashboard"
TAG = "admdash"


def item(**changes) -> ModerationItemOut:  # type: ignore[no-untyped-def]
    base = {
        "id": uuid.uuid4(),
        "target_type": "post",
        "target_id": uuid.uuid4(),
        "reason": "spam",
        "report_count": 1,
        "created_at": datetime(2026, 10, 1, tzinfo=UTC),
    }
    return ModerationItemOut(**{**base, **changes})


# --------------------------------------------------------------------------- pure helpers


def test_day_labels_show_the_month_on_the_first_day_and_on_the_1st() -> None:
    days = [date(2026, 9, 24) + timedelta(days=n) for n in range(14)]
    assert day_labels(days) == [
        "24 Sep", "25", "26", "27", "28", "29", "30", "1 Oct", "2", "3", "4", "5", "6", "7",
    ]  # fmt: skip


def test_percent_delta() -> None:
    assert percent_delta(110, 100, "week") == ("+10.0% vs last week", "good")
    assert percent_delta(90, 100, "week") == ("-10.0% vs last week", "bad")
    assert percent_delta(5, 0, "week") == ("New this week", "good")
    assert percent_delta(0, 0, "week") == ("No change", "good")


def test_report_cards() -> None:
    spam = report_card(item(group_name="Unit 6 · Genetics", ai_flag_score=0.96))
    assert spam.model_dump() == {
        "title": "Spam post",
        "subtitle": "Group · Unit 6 · Genetics",
        "meta": "AI flagged",
        "severity": "high",
    }
    visual = report_card(item(target_type="visual", reason="unclear", report_count=2,
                              visual_title="Nephron labelled diagram"))  # fmt: skip
    assert (visual.title, visual.subtitle, visual.meta, visual.severity) == (
        "Unclear diagram",
        "Nephron labelled diagram",
        "2 reports",
        "medium",
    )
    reply = report_card(item(target_type="reply", reason="other", author_handle="kavindu"))
    assert (reply.subtitle, reply.severity) == ("Reply by kavindu", None)


# --------------------------------------------------------------------------- auth


async def test_login_and_admin_role_needed(anon_client, client) -> None:
    assert (await anon_client.get(URL)).status_code == 401
    forbidden = await client.get(URL)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "FORBIDDEN"


async def test_unknown_dashboard_path_is_404(admin_client) -> None:
    response = await admin_client.get(f"{URL}/extra")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_post_is_not_allowed(admin_client) -> None:
    assert (await admin_client.post(URL, json={})).status_code == 405


# --------------------------------------------------------------------------- with data


@pytest.fixture
async def activity(db_session, admin_in_db):  # type: ignore[no-untyped-def]
    """A student active today with a finished quiz, an old AI question, a note, a report."""
    now, today = clock.now(), clock.today()
    student = User(firebase_uid=f"{TAG}-s", email=f"s.{TAG}@test.local",
                   display_name="Nethmi Perera", role=UserRole.STUDENT)  # fmt: skip
    db_session.add(student)
    await db_session.flush()
    unit = Unit(number=200_000 + uuid.uuid4().int % 99_999, title="Genetics")
    db_session.add(unit)
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="6.1", title="Mendel")
    paper = Paper(title=f"Quiz {TAG}", created_by=student.id)
    db_session.add_all([topic, paper])
    await db_session.flush()
    post = Post(author_id=student.id, title="Leaked paper", body="join")
    db_session.add_all(
        [
            StudentProfile(user_id=student.id, exam_year=today.year + 1),
            StudyActivity(user_id=student.id, activity_date=today),
            Question(unit_id=unit.id, topic_id=topic.id, question_type=QuestionType.MCQ,
                     stem=f"Old AI question {TAG}", source="ai",
                     status=ContentStatus.PENDING_REVIEW,
                     created_at=now - timedelta(hours=72)),
            Note(topic_id=topic.id, title="Mendel note", body_md="x",
                 status=ContentStatus.PENDING_REVIEW, source=ContentSource.AI),
            post,
        ]
    )  # fmt: skip
    await db_session.flush()
    db_session.add(ContentReport(reporter_id=student.id, target_type="post",
                                 target_id=post.id, reason="spam"))  # fmt: skip
    # A finished quiz: 5 MCQs of the topic, 4 answered wrong with the same misconception.
    attempt = Attempt(paper_id=paper.id, user_id=student.id, status="graded", submitted_at=now)
    wrong_idea = Misconception(title=f"Assumes independent assortment {TAG}")
    db_session.add_all([attempt, wrong_idea])
    await db_session.flush()
    for n in range(5):
        q = Question(unit_id=unit.id, topic_id=topic.id, question_type=QuestionType.MCQ,
                     stem=f"Cross {n} {TAG}", source="admin", status=ContentStatus.APPROVED)  # fmt: skip
        db_session.add(q)
        await db_session.flush()
        right = MCQOption(question_id=q.id, label="A", text="9:3:3:1", is_correct=True)
        wrong = MCQOption(question_id=q.id, label="B", text="1:1", is_correct=False,
                          misconception_id=wrong_idea.id)  # fmt: skip
        db_session.add_all([right, wrong])
        await db_session.flush()
        chosen = right if n == 0 else wrong
        db_session.add(Response(attempt_id=attempt.id, question_id=q.id,
                                selected_option_id=chosen.id, is_correct=n == 0))  # fmt: skip
    await db_session.commit()
    ids = {"unit": unit.id, "topic": topic.id, "post": post.id, "student": student.id,
           "misconception": wrong_idea.id}  # fmt: skip
    yield ids
    await db_session.rollback()
    await db_session.execute(delete(ContentReport).where(ContentReport.target_id == ids["post"]))
    await db_session.execute(delete(Note).where(Note.topic_id == ids["topic"]))
    await db_session.execute(delete(Question).where(Question.unit_id == ids["unit"]))
    await db_session.execute(delete(Paper).where(Paper.created_by == ids["student"]))
    await db_session.execute(delete(Post).where(Post.id == ids["post"]))
    await db_session.execute(delete(Unit).where(Unit.id == ids["unit"]))
    await db_session.execute(delete(Misconception).where(Misconception.id == ids["misconception"]))
    await db_session.execute(delete(User).where(User.email.like(f"%{TAG}%")))
    await db_session.commit()


@pytest.mark.db
async def test_dashboard_shape_and_numbers(admin_client, activity) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.get(URL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"title", "message", "batch_label", "kpis", "activity",
                         "recent_reports", "missed_topics_attempts", "missed_topics"}  # fmt: skip
    assert (body["title"], body["message"]) == ("Dashboard", None)
    assert body["batch_label"].startswith("A/L ") and body["batch_label"].endswith(" batch")

    kpis = {k["kind"]: k for k in body["kpis"]}
    assert list(kpis) == ["students", "quizzes", "aiReview", "reports"]
    for kpi in kpis.values():
        assert set(kpi) == {"kind", "label", "value", "delta", "trend", "sparkline"}
        assert len(kpi["sparkline"]) == 8
        assert kpi["trend"] in {"good", "bad", "warning"}
    assert kpis["students"]["value"] >= 1
    assert kpis["students"]["sparkline"][-1] >= 1  # today
    assert kpis["quizzes"]["value"] >= 1
    assert kpis["quizzes"]["delta"].endswith("vs yesterday")
    assert kpis["aiReview"]["value"] >= 2  # the question + the note
    assert kpis["aiReview"]["trend"] == "warning"  # the question waits over 48 h
    assert "older than 48h" in kpis["aiReview"]["delta"]
    assert kpis["reports"]["value"] >= 1

    act = body["activity"]
    assert len(act["day_labels"]) == len(act["quizzes"]) == len(act["notes_generated"]) == 14
    assert act["quizzes"][-1] >= 1 and act["notes_generated"][-1] >= 1
    assert " " in act["day_labels"][0]  # "24 Sep"

    assert 1 <= len(body["recent_reports"]) <= 5
    assert set(body["recent_reports"][0]) == {"title", "subtitle", "meta", "severity"}
    assert body["missed_topics_attempts"] >= 5
    assert len(body["missed_topics"]) <= 5
    [mendel] = [t for t in body["missed_topics"] if t["unit"].endswith("· Genetics")
                and t["topic"] == "Mendel"]  # fmt: skip
    assert set(mendel) == {"topic", "unit", "miss_rate", "attempts", "top_misconception"}
    assert (mendel["miss_rate"], mendel["attempts"]) == (0.8, 5)
    assert mendel["top_misconception"] == f"Assumes independent assortment {TAG}"
    assert mendel["unit"].startswith("Unit ")
