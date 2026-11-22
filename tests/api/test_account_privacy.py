"""Privacy: DELETE /auth/me removes ALL of a student's data, GET /auth/me/export gives a copy.

Two students get the same kind of data (profile, attempts, evaluations, plan, notes, posts...)
and talk to each other in the community. Deleting student 1 must leave no row of theirs in
any table, ask Storage to delete their files, and keep student 2's data (scores and reply
counts of student 2's posts are corrected).
"""

import json
import uuid
from datetime import date

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import firebase_users, storage
from api.core.errors import ServiceUnavailableError
from shared.db.base import Base
from shared.db.models import (
    AIJob,
    Attempt,
    CommunityGroup,
    Concept,
    ConceptMastery,
    ContentReport,
    DailyPlanItem,
    DeviceToken,
    EmailCode,
    Evaluation,
    GroupMember,
    LibraryItem,
    Mistake,
    Note,
    Notification,
    Paper,
    PaperQuestion,
    PlanItem,
    Post,
    Question,
    QuestionReport,
    Recommendation,
    Reply,
    Response,
    StudentProfile,
    StudyPlan,
    Summary,
    Topic,
    TopicBookmark,
    Unit,
    Upload,
    User,
    UserAchievement,
    UserSettings,
    Visual,
    VisualReport,
    Vote,
)
from shared.enums import (
    AttemptKind,
    ContentStatus,
    DevicePlatform,
    JobType,
    MistakeType,
    ModerationStatus,
    NotificationType,
    QuestionType,
    UserRole,
    VisualKind,
)
from tests.conftest import STUDENT, make_api_client, student_claims

pytestmark = pytest.mark.db

EXPORT_KEYS = {
    "exported_at",
    "account",
    "profile",
    "settings",
    "privacy",
    "achievements",
    "quiz_attempts",
    "exam_attempts",
    "evaluations",
    "mistakes",
    "recommendations",
    "study_plan",
    "notes",
    "uploads",
    "bookmarks",
    "community",
    "notifications",
}


# --------------------------------------------------------------------------- test data


async def _seed_student(session: AsyncSession, user_id: uuid.UUID, shared: dict) -> dict:
    """One student's data in every module. Returns the ids the tests look at."""
    tag = user_id.hex[:8]
    session.add_all(
        [
            StudentProfile(user_id=user_id, school="Royal College", exam_year=2027),
            UserSettings(user_id=user_id),
            DeviceToken(user_id=user_id, fcm_token=f"fcm-{tag}", platform=DevicePlatform.ANDROID),
            Notification(
                user_id=user_id, type=NotificationType.JOB_DONE, title="Done", body="Your plan"
            ),
            TopicBookmark(user_id=user_id, topic_id=shared["topic"]),
            Mistake(
                user_id=user_id,
                question_id=shared["question"],
                mistake_type=MistakeType.KNOWLEDGE_GAP,
            ),
            ConceptMastery(user_id=user_id, concept_id=shared["concept"], mastery_score=0.5),
            DailyPlanItem(
                user_id=user_id,
                plan_date=date(2026, 11, 18),
                position=1,
                kind="read",
                title="Read osmosis",
                minutes=10,
            ),
            GroupMember(group_id=shared["group"], user_id=user_id),
            UserAchievement(
                user_id=user_id, achievement_id="streak_7", unlocked_at=func.now(), detail=tag
            ),
            QuestionReport(question_id=shared["question"], user_id=user_id, reason="wrong_answer"),
            VisualReport(visual_id=shared["visual"], user_id=user_id, reason="unclear"),
            EmailCode(
                user_id=user_id,
                email=f"{tag}@test.local",
                purpose="verify_email",
                code_hash="x" * 64,
                expires_at=func.now(),
            ),
        ]
    )
    # Quiz + exam attempts on a personal paper
    paper = Paper(title=f"Quiz {tag}", paper_type="quiz", created_by=user_id)
    session.add(paper)
    await session.flush()
    session.add(PaperQuestion(paper_id=paper.id, question_id=shared["question"], position=1))
    quiz = Attempt(paper_id=paper.id, user_id=user_id, kind=AttemptKind.QUIZ, status="graded")
    exam = Attempt(paper_id=paper.id, user_id=user_id, kind=AttemptKind.EXAM, status="evaluated")
    session.add_all([quiz, exam])
    await session.flush()
    session.add(Response(attempt_id=quiz.id, question_id=shared["question"], is_correct=False))

    evaluation = Evaluation(
        user_id=user_id,
        question_id=shared["question"],
        answer_text="Water moves",
        answer_image_path=f"answers/{user_id}/{uuid.uuid4()}/page-1.jpg",
    )
    plan = StudyPlan(user_id=user_id, title=f"Plan {tag}")
    recommendation = Recommendation(user_id=user_id, reason="Weak on osmosis")
    upload = Upload(user_id=user_id, file_name="my.pdf", file_path=f"uploads/{user_id}/u.pdf")
    note = Note(
        topic_id=shared["topic"], user_id=user_id, title=f"My note {tag}", body_md="Osmosis..."
    )
    job = AIJob(job_type=JobType.EVALUATE_ANSWER, input={"answer": "secret"}, requested_by=user_id)
    post = Post(
        group_id=shared["group"],
        author_id=user_id,
        title=f"Post by {tag}",
        body="Why does osmosis happen?",
        image_paths=[f"posts/{tag}/1.jpg"],
        moderation_status=ModerationStatus.APPROVED,
    )
    # Own AI visuals: one still waiting for review (private), one approved (shared content).
    draft_visual = Visual(
        topic_id=shared["topic"],
        kind=VisualKind.ILLUSTRATION,
        title=f"My visual {tag}",
        prompt=f"draw osmosis {tag}",
        image_path=f"visuals/{tag}/draft.png",
        is_ai_generated=True,
        status=ContentStatus.PENDING_REVIEW,
        created_by=user_id,
    )
    approved_visual = Visual(
        topic_id=shared["topic"],
        kind=VisualKind.ILLUSTRATION,
        title=f"Approved visual {tag}",
        image_path=f"visuals/{tag}/approved.png",
        is_ai_generated=True,
        status=ContentStatus.APPROVED,
        created_by=user_id,
    )
    session.add_all(
        [evaluation, plan, recommendation, upload, note, job, post, draft_visual, approved_visual]
    )
    await session.flush()
    session.add_all(
        [
            PlanItem(
                study_plan_id=plan.id, title="Revise osmosis", recommendation_id=recommendation.id
            ),
            Summary(user_id=user_id, upload_id=upload.id, body_md="Short summary"),
            LibraryItem(user_id=user_id, item_type="note", item_id=note.id, title="Saved note"),
        ]
    )
    await session.flush()
    return {
        "paper": paper.id,
        "post": post.id,
        "job": job.id,
        "upload": upload.id,
        "draft_visual": draft_visual.id,
        "approved_visual": approved_visual.id,
    }


@pytest.fixture
async def two_students(student_in_db, db_session: AsyncSession):
    """Student 1 (STUDENT, the one who deletes) and student 2, with data that touches."""
    s = db_session
    other_id = uuid.uuid4()
    s.add(
        User(
            id=other_id,
            firebase_uid=f"other-{other_id.hex[:8]}",
            email=f"other-{other_id.hex[:8]}@test.local",
            display_name="Kasun",
            role=UserRole.STUDENT,
        )
    )
    unit = Unit(number=700_000 + uuid.uuid4().int % 99_999, title="Privacy unit")
    s.add(unit)
    await s.flush()
    unit_id = unit.id
    topic = Topic(unit_id=unit.id, number="1.1", title="Osmosis")
    s.add(topic)
    await s.flush()
    concept = Concept(topic_id=topic.id, name="Water potential")
    question = Question(
        unit_id=unit.id, topic_id=topic.id, question_type=QuestionType.MCQ, stem="Osmosis is?"
    )
    group = CommunityGroup(name=f"Privacy {other_id.hex[:6]}")
    admin_visual = Visual(
        topic_id=topic.id,
        kind=VisualKind.DIAGRAM,
        title="Osmosis diagram",
        mermaid_code="graph TD; A-->B",
        status=ContentStatus.APPROVED,
    )
    s.add_all([concept, question, group, admin_visual])
    await s.flush()
    shared = {
        "topic": topic.id,
        "concept": concept.id,
        "question": question.id,
        "group": group.id,
        "visual": admin_visual.id,
    }

    mine = await _seed_student(s, STUDENT.id, shared)
    theirs = await _seed_student(s, other_id, shared)

    # Student 1 answers student 2's post (accepted), votes on it, and reports it.
    my_reply = Reply(
        post_id=theirs["post"],
        author_id=STUDENT.id,
        body="Because of water potential",
        is_accepted=True,
        moderation_status=ModerationStatus.APPROVED,
    )
    s.add(my_reply)
    await s.flush()
    their_post = await s.get(Post, theirs["post"])
    their_post.accepted_reply_id = my_reply.id
    their_post.reply_count = 1
    their_post.score = 1
    s.add(Vote(user_id=STUDENT.id, post_id=theirs["post"], value=1))
    s.add(
        ContentReport(
            reporter_id=STUDENT.id, target_type="post", target_id=theirs["post"], reason="spam"
        )
    )
    # Student 2 votes on student 1's post and reports it (goes away with the post).
    s.add(Vote(user_id=other_id, post_id=mine["post"], value=1))
    s.add(
        ContentReport(reporter_id=other_id, target_type="post", target_id=mine["post"], reason="x")
    )
    await s.commit()

    my_reply_id = my_reply.id
    yield {"other": other_id, "mine": mine, "theirs": theirs, "my_reply": my_reply_id, **shared}

    # Clean up student 2 and the shared rows (student 1 is removed by student_in_db).
    await s.rollback()
    await s.execute(delete(Post).where(Post.group_id == shared["group"]))
    await s.execute(delete(Paper).where(Paper.created_by.in_([other_id, STUDENT.id])))
    await s.execute(delete(AIJob).where(AIJob.requested_by.in_([other_id, STUDENT.id])))
    await s.execute(delete(User).where(User.id == other_id))
    await s.execute(delete(EmailCode).where(EmailCode.email.like(f"{other_id.hex[:8]}%")))
    await s.execute(delete(CommunityGroup).where(CommunityGroup.id == shared["group"]))
    await s.execute(delete(Note).where(Note.topic_id == shared["topic"]))  # RESTRICT on topic
    await s.execute(delete(Visual).where(Visual.topic_id == shared["topic"]))  # RESTRICT too
    await s.execute(delete(Question).where(Question.id == shared["question"]))
    await s.execute(delete(Unit).where(Unit.id == unit_id))  # topic + concept cascade
    await s.commit()


async def _rows_per_user_column(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """For EVERY column in the schema that points to users.id: rows that point to `user_id`."""
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if any(fk.column.table.name == "users" for fk in column.foreign_keys):
                n = await session.scalar(
                    select(func.count()).select_from(table).where(column == user_id)
                )
                counts[f"{table.name}.{column.name}"] = n or 0
    counts["users.id"] = (
        await session.scalar(select(func.count()).select_from(User).where(User.id == user_id)) or 0
    )
    return counts


@pytest.fixture
def storage_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Replaces Storage deletes; returns the path lists it was called with."""
    calls: list[list[str]] = []

    def delete_files(paths: list[str]) -> int:
        calls.append(list(paths))
        return 0

    monkeypatch.setattr(storage, "delete_files", delete_files)
    return calls


# --------------------------------------------------------------------------- DELETE /auth/me


async def test_delete_me_removes_every_row_and_file(
    two_students, fake_firebase, storage_calls, db_session
):
    other = two_students["other"]
    mine = two_students["mine"]
    before = await _rows_per_user_column(db_session, STUDENT.id)
    assert sum(before.values()) > 25  # the seed really covers many tables
    other_before = await _rows_per_user_column(db_session, other)

    async with make_api_client(claims=student_claims()) as c:
        response = await c.delete("/api/v1/auth/me")
    assert response.status_code == 204
    assert ("delete_user", STUDENT.firebase_uid, {}) in fake_firebase

    db_session.expire_all()
    # No table has a row of student 1 left (also the SET NULL ones: checked by id below).
    after = await _rows_per_user_column(db_session, STUDENT.id)
    assert {k: v for k, v in after.items() if v} == {}
    assert await db_session.get(Post, mine["post"]) is None
    assert await db_session.get(Reply, two_students["my_reply"]) is None
    assert await db_session.get(AIJob, mine["job"]) is None
    assert await db_session.get(Paper, mine["paper"]) is None
    assert await db_session.get(Upload, mine["upload"]) is None
    assert await db_session.get(Visual, mine["draft_visual"]) is None  # private: gone
    kept = await db_session.get(Visual, mine["approved_visual"])  # shared content: unlinked
    assert kept is not None and kept.created_by is None
    assert await db_session.get(Visual, two_students["visual"]) is not None
    reports_on_my_post = await db_session.scalar(
        select(func.count())
        .select_from(ContentReport)
        .where(ContentReport.target_id == mine["post"])
    )
    assert reports_on_my_post == 0

    # Storage: answer photos, PDF uploads, Learn uploads and post images, after the commit.
    assert len(storage_calls) == 1
    paths = storage_calls[0]
    assert f"answers/{STUDENT.id}/" in paths
    assert f"uploads/{STUDENT.id}/" in paths
    assert any(p.endswith(f"/{STUDENT.id}/") and "learn" in p for p in paths)
    assert f"posts/{STUDENT.id.hex[:8]}/1.jpg" in paths
    assert f"visuals/{STUDENT.id.hex[:8]}/draft.png" in paths
    assert f"visuals/{STUDENT.id.hex[:8]}/approved.png" not in paths
    assert not any(other.hex[:8] in p or str(other) in p for p in paths)

    # Student 2 keeps everything, except their vote + report on student 1's (deleted) post.
    other_after = await _rows_per_user_column(db_session, other)
    changed = {k: (other_before[k], v) for k, v in other_after.items() if other_before[k] != v}
    assert changed == {"votes.user_id": (1, 0), "content_reports.reporter_id": (1, 0)}
    their_post = await db_session.get(Post, two_students["theirs"]["post"])
    assert their_post is not None
    assert (their_post.score, their_post.reply_count, their_post.accepted_reply_id) == (0, 0, None)


async def test_delete_me_keeps_everything_when_firebase_fails(
    two_students, storage_calls, db_session, monkeypatch
):
    async def broken_delete(uid):  # type: ignore[no-untyped-def]
        raise ServiceUnavailableError("down", code="FIREBASE_ERROR")

    monkeypatch.setattr(firebase_users, "delete_user", broken_delete)
    before = await _rows_per_user_column(db_session, STUDENT.id)

    async with make_api_client(claims=student_claims()) as c:
        response = await c.delete("/api/v1/auth/me")

    assert response.status_code == 503
    db_session.expire_all()
    assert await _rows_per_user_column(db_session, STUDENT.id) == before
    assert await db_session.get(Post, two_students["mine"]["post"]) is not None
    assert storage_calls == []  # no file is deleted when the account stays


async def test_storage_delete_files_local_folder(tmp_path, monkeypatch):
    """Dev without a bucket: a folder path removes the folder, never outside the root."""
    from api.core.config import get_settings

    monkeypatch.setattr(get_settings(), "STORAGE_BUCKET", "")
    monkeypatch.setattr(get_settings(), "LOCAL_STORAGE_DIR", str(tmp_path))
    (tmp_path / "answers" / "u1" / "x").mkdir(parents=True)
    (tmp_path / "answers" / "u1" / "x" / "page-1.jpg").write_bytes(b"jpg")
    (tmp_path / "answers" / "u2").mkdir()

    failed = storage.delete_files(["answers/u1/", "missing/file.jpg", "../outside/"])

    assert not (tmp_path / "answers" / "u1").exists()
    assert (tmp_path / "answers" / "u2").exists()
    assert failed == 1  # "../outside/" is refused


# --------------------------------------------------------------------------- GET /auth/me/export


async def test_export_has_the_shape_and_only_my_data(two_students):
    async with make_api_client(claims=student_claims()) as c:
        response = await c.get("/api/v1/auth/me/export")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == EXPORT_KEYS
    assert data["account"]["id"] == str(STUDENT.id)
    assert data["account"]["email"] == STUDENT.email
    assert data["profile"]["school"] == "Royal College"
    assert data["settings"]["theme"] == "system"
    assert data["privacy"]["push_devices"] == 1
    assert data["privacy"]["improve_ai"] is True
    assert data["privacy"]["share_research"] is False
    assert "improve_ai" not in data["settings"]
    assert [(a["id"], a["detail"]) for a in data["achievements"]] == [
        ("streak_7", STUDENT.id.hex[:8])
    ]
    assert [b["topic_id"] for b in data["bookmarks"]] == [str(two_students["topic"])]
    assert data["bookmarks"][0]["topic_title"] == "Osmosis"
    assert [(n["title"], n["body"]) for n in data["notifications"]] == [("Done", "Your plan")]
    assert [a["kind"] for a in data["quiz_attempts"]] == ["quiz"]
    assert [a["kind"] for a in data["exam_attempts"]] == ["exam"]
    assert len(data["quiz_attempts"][0]["answers"]) == 1
    assert data["evaluations"][0]["answer_image_path"].startswith(f"answers/{STUDENT.id}/")
    assert len(data["mistakes"]) == 1
    assert len(data["recommendations"]) == 1
    assert data["study_plan"]["plans"][0]["items"][0]["title"] == "Revise osmosis"
    assert len(data["study_plan"]["daily_items"]) == 1
    assert data["notes"][0]["title"].startswith("My note")
    assert data["uploads"][0]["file_path"] == f"uploads/{STUDENT.id}/u.pdf"
    assert data["uploads"][0]["summaries"][0]["body_md"] == "Short summary"
    assert [p["id"] for p in data["community"]["posts"]] == [str(two_students["mine"]["post"])]
    assert [r["id"] for r in data["community"]["replies"]] == [str(two_students["my_reply"])]

    # Nothing of student 2, and no secrets.
    text = json.dumps(data)
    other = two_students["other"]
    assert str(other) not in text
    assert other.hex[:8] not in text
    # Student 1's reply points to student 2's post: only its id is in the export, not its text.
    assert f"Post by {other.hex[:8]}" not in text
    for secret in (STUDENT.firebase_uid, "fcm-", "x" * 64, "code_hash", "secret"):
        assert secret not in text


async def test_export_needs_a_token(anon_client):
    response = await anon_client.get("/api/v1/auth/me/export")
    assert response.status_code == 401


async def test_export_before_register_is_404(no_student_row):
    async with make_api_client(claims=student_claims()) as c:
        response = await c.get("/api/v1/auth/me/export")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


@pytest.fixture
async def no_student_row(db_session: AsyncSession):
    from tests.conftest import delete_test_user

    await delete_test_user(db_session)
    yield
    await delete_test_user(db_session)
