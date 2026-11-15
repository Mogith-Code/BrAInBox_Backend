"""Admin quality review: GET /admin/questions/quality and POST /{id}/review. Owner: Udith."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from api.core import clock
from api.modules.quality.service import check_from_ai
from shared.db.models import MCQOption, Question, QuestionReport, QuestionReview, Topic, Unit, User
from shared.enums import ContentStatus, QuestionType, UserRole

QUEUE = "/api/v1/admin/questions/quality"
TAG = "admqual"


def review_url(question_id: object) -> str:
    return f"/api/v1/admin/questions/{question_id}/review"


@pytest.fixture
async def queue(db_session, admin_in_db):  # type: ignore[no-untyped-def]
    """Three AI questions waiting: AI-checked + reported, no correct option, a duplicate."""
    unit = Unit(number=300_000 + uuid.uuid4().int % 99_999, title="Genetics")
    db_session.add(unit)
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="6.2", title="Linkage")
    db_session.add(topic)
    reporter = User(firebase_uid=f"{TAG}-r", email=f"r.{TAG}@test.local", role=UserRole.STUDENT)
    db_session.add(reporter)
    await db_session.flush()
    stem = f"Which genes are linked? {TAG}"
    old = clock.now() - timedelta(hours=5)

    def mcq(text: str, **kw):  # type: ignore[no-untyped-def]
        return Question(unit_id=unit.id, topic_id=topic.id, question_type=QuestionType.MCQ,
                        stem=text, source="ai", **{"status": ContentStatus.PENDING_REVIEW, **kw})  # fmt: skip

    checked = mcq(f"Recombination frequency? {TAG}", created_at=old)
    no_correct = mcq(f"Map distance? {TAG}", created_at=old + timedelta(minutes=1))
    duplicate = mcq(stem, created_at=old + timedelta(minutes=2))
    original = Question(unit_id=unit.id, question_type=QuestionType.MCQ, stem=stem.upper(),
                        source="admin", status=ContentStatus.APPROVED)  # fmt: skip
    approved_ai = mcq(f"Not waiting {TAG}", status=ContentStatus.APPROVED)
    db_session.add_all([checked, no_correct, duplicate, original, approved_ai])
    await db_session.flush()
    for q, correct in [(checked, "A"), (no_correct, ""), (duplicate, "A")]:
        for label in "AB":
            db_session.add(MCQOption(question_id=q.id, label=label, text=label,
                                     is_correct=label == correct))  # fmt: skip
    db_session.add_all(
        [
            QuestionReview(question_id=checked.id, reviewer_type="ai", verdict="revise",
                           checks={"single_correct_answer": True,
                                   "distractor_quality": {"result": "review",
                                                          "note": "Option B is too obvious"},
                                   "in_syllabus": "pass", "duplicate_check": True}),
            QuestionReport(question_id=checked.id, user_id=reporter.id, reason="wrong_answer"),
            QuestionReport(question_id=checked.id, user_id=reporter.id, reason="wrong_answer"),
            QuestionReport(question_id=checked.id, user_id=reporter.id, reason="typo"),
        ]
    )  # fmt: skip
    await db_session.commit()
    ids = {"unit": unit.id, "checked": checked.id, "no_correct": no_correct.id,
           "duplicate": duplicate.id, "original": original.id, "original_number": original.number}  # fmt: skip
    yield ids
    await db_session.rollback()
    await db_session.execute(delete(Question).where(Question.unit_id == ids["unit"]))
    await db_session.execute(delete(Unit).where(Unit.id == ids["unit"]))
    await db_session.execute(delete(User).where(User.email.like(f"%{TAG}%")))
    await db_session.commit()


def mine(body: dict, ids: dict) -> list[dict]:
    wanted = {str(ids[k]) for k in ("checked", "no_correct", "duplicate")}
    return [i for i in body["items"] if i["id"] in wanted]


def test_ai_check_values() -> None:
    assert check_from_ai("Syllabus match", True).result == "pass"
    assert check_from_ai("Syllabus match", "fail").result == "fail"
    review = check_from_ai("Distractor quality", {"result": "review", "note": "B is obvious"})
    assert (review.result, review.note) == ("review", "B is obvious")
    assert check_from_ai("Syllabus match", 42) is None


async def test_login_and_admin_role_needed(anon_client, client) -> None:
    assert (await anon_client.get(QUEUE)).status_code == 401
    assert (await client.get(QUEUE)).status_code == 403
    some = review_url(uuid.uuid4())
    assert (await anon_client.post(some, json={"approve": True})).status_code == 401
    assert (await client.post(some, json={"approve": True})).status_code == 403


async def test_bad_review_body_is_422(admin_client) -> None:
    assert (await admin_client.post(review_url(uuid.uuid4()), json={})).status_code == 422
    assert (await admin_client.post(review_url("x"), json={"approve": True})).status_code == 422


@pytest.mark.db
async def test_queue_checks_and_reports(admin_client, queue) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.get(QUEUE)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"in_queue", "auto_check_failed", "with_student_reports",
                         "avg_review_minutes", "items"}  # fmt: skip
    items = mine(body, queue)
    assert [i["id"] for i in items] == [
        str(queue[k]) for k in ("checked", "no_correct", "duplicate")
    ]
    checked, no_correct, duplicate = items
    assert set(checked) == {"id", "code", "stem", "unit_number", "topic_code", "checks",
                            "student_reports"}  # fmt: skip
    assert checked["topic_code"] == "6.2"
    assert [c["name"] for c in checked["checks"]] == [
        "Single correct answer", "Distractor quality", "Syllabus match", "Duplicate check",
    ]  # fmt: skip
    assert [c["result"] for c in checked["checks"]] == ["pass", "review", "pass", "pass"]
    assert checked["checks"][1]["note"] == "Option B is too obvious"
    assert checked["student_reports"] == [
        {"text": "Wrong answer key", "count": 2},
        {"text": "Typo", "count": 1},
    ]
    # Not AI-checked: our rules
    assert no_correct["checks"][0] == {
        "name": "Single correct answer", "result": "fail",
        "note": "0 of 2 options are marked correct.",
    }  # fmt: skip
    assert no_correct["checks"][1] == {
        "name": "Distractor quality", "result": "review",
        "note": "Not checked by the AI reviewer yet.",
    }  # fmt: skip
    assert duplicate["checks"][3]["result"] == "fail"
    assert duplicate["checks"][3]["note"] == f"Same text as Q-{queue['original_number']}."
    assert body["in_queue"] >= 3
    assert body["auto_check_failed"] >= 2 and body["with_student_reports"] >= 1


@pytest.mark.db
async def test_review_approve_reject_and_review_time(admin_client, queue, db_session) -> None:  # type: ignore[no-untyped-def]
    rejected = await admin_client.post(review_url(queue["no_correct"]), json={"approve": False})
    # The checked one has no misconception on its wrong option, so it can't be published yet.
    incomplete = await admin_client.post(review_url(queue["checked"]), json={"approve": True})

    assert rejected.status_code == 204
    assert incomplete.status_code == 422
    assert incomplete.json()["error"]["code"] == "QUESTION_INCOMPLETE"
    row = await db_session.get(Question, queue["no_correct"], populate_existing=True)
    assert row.status == ContentStatus.REJECTED
    verdicts = (
        (
            await db_session.execute(
                select(QuestionReview.verdict).where(
                    QuestionReview.question_id == queue["no_correct"],
                    QuestionReview.reviewer_type == "admin",
                )
            )
        )
        .scalars()
        .all()
    )
    assert verdicts == ["reject"]
    body = (await admin_client.get(QUEUE)).json()
    assert str(queue["no_correct"]) not in {i["id"] for i in body["items"]}
    assert body["avg_review_minutes"] is not None and body["avg_review_minutes"] >= 290


@pytest.mark.db
async def test_review_unknown_question_is_404(admin_client, admin_in_db) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.post(review_url(uuid.uuid4()), json={"approve": False})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "QUESTION_NOT_FOUND"
