"""Notification center: GET /notifications, PATCH /notifications/{id}, POST read-all, and the
notifications other modules create (job finished, study plan, community reply). Owner: Mogith."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from api.core import jobs
from api.modules.community import service as community_service
from api.modules.notifications import service
from shared.db.models import AIJob, CommunityGroup, Notification, Post, Reply, User
from shared.enums import JobStatus, JobType, ModerationStatus, NotificationType, UserRole
from tests.conftest import STUDENT

URL = "/api/v1/notifications"


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)


def _job(job_type: JobType, status: JobStatus, requested_by=STUDENT.id) -> AIJob:  # type: ignore[no-untyped-def]
    return AIJob(id=uuid.uuid4(), job_type=job_type, status=status, requested_by=requested_by)


# --------------------------------------------------------------------------- no database


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", URL), ("post", f"{URL}/read-all"), ("patch", f"{URL}/{uuid.uuid4()}")],
)
async def test_notifications_need_login(anon_client, method, path):
    response = await anon_client.request(method, path, json={"read": True})
    assert response.status_code == 401


async def test_bad_requests_are_422(client):
    assert (await client.patch(f"{URL}/not-an-id", json={"read": True})).status_code == 422
    assert (await client.patch(f"{URL}/{uuid.uuid4()}", json={})).status_code == 422
    assert (await client.get(URL, params={"limit": 0})).status_code == 422


def test_notification_out_matches_the_app_model():
    row = Notification(
        id=uuid.uuid4(),
        user_id=STUDENT.id,
        type=NotificationType.COMMUNITY_REPLY,
        title="New reply",
        body="Hi",
        data={"post_id": "p1", "ai_generated": True},
        created_at=datetime(2026, 11, 17, tzinfo=UTC),
        read_at=None,
    )
    out = service.notification_out(row).model_dump(mode="json")
    assert out["type"] == "community" and out["event"] == "community_reply"
    assert (out["read"], out["ai_generated"], out["data"]) == (False, True, {"post_id": "p1"})
    assert service.KIND_OF[NotificationType.PLAN_READY] == "reminder"
    assert set(service.KIND_OF) == set(NotificationType)  # every event has an app kind


async def test_student_jobs_notify_when_they_finish():
    session = FakeSession()
    await service.on_job_finished(session, _job(JobType.GENERATE_NOTES, JobStatus.SUCCEEDED))  # type: ignore[arg-type]
    await service.on_job_finished(session, _job(JobType.GENERATE_VISUAL, JobStatus.FAILED))  # type: ignore[arg-type]
    [done, failed] = session.added
    assert isinstance(done, Notification) and done.type == NotificationType.JOB_DONE
    assert done.title == "Your notes are ready" and done.data["ai_generated"] is True
    assert done.data["screen"] == "notes" and done.user_id == STUDENT.id
    assert failed.title == "We couldn't make your visual"  # type: ignore[attr-defined]
    assert "ai_generated" not in failed.data  # type: ignore[attr-defined]


async def test_other_jobs_do_not_notify():
    session = FakeSession()
    for job in [
        _job(JobType.RAG_INGEST, JobStatus.SUCCEEDED),  # admin job
        _job(JobType.BUILD_PAPER, JobStatus.SUCCEEDED),  # the app waits for it
        _job(JobType.GENERATE_NOTES, JobStatus.RUNNING),  # not finished
        _job(JobType.GENERATE_NOTES, JobStatus.SUCCEEDED, requested_by=None),
    ]:
        await service.on_job_finished(session, job)  # type: ignore[arg-type]
    assert session.added == []


def test_preview_is_one_short_line():
    assert service.preview("  a\n b  ") == "a b"
    assert len(service.preview("x" * 200, 20)) == 20


# --------------------------------------------------------------------------- database


async def _add(db_session, **extra) -> Notification:  # type: ignore[no-untyped-def]
    fields = {"type": NotificationType.SYSTEM, "title": "t", "body": "b", **extra}
    row = Notification(user_id=STUDENT.id, **fields)
    db_session.add(row)
    await db_session.commit()
    return row


@pytest.mark.db
async def test_list_mark_read_and_read_all(client, db_session, student_in_db):
    old = await _add(db_session, title="Old")
    new = await _add(db_session, title="New", type=NotificationType.PLAN_READY)
    other = User(firebase_uid=f"notif-{uuid.uuid4().hex[:8]}", role=UserRole.STUDENT)
    db_session.add(other)
    await db_session.commit()
    theirs = Notification(user_id=other.id, type=NotificationType.SYSTEM, title="x", body="")
    db_session.add(theirs)
    await db_session.commit()
    try:
        listed = (await client.get(URL)).json()
        assert [n["title"] for n in listed["items"]] == ["New", "Old"]  # newest first, mine only
        assert listed["unread_count"] == 2
        assert listed["items"][0]["type"] == "reminder"

        read = await client.patch(f"{URL}/{old.id}", json={"read": True})
        assert (read.status_code, read.json()["read"]) == (200, True)
        unread_only = (await client.get(URL, params={"unread_only": True})).json()
        assert [n["id"] for n in unread_only["items"]] == [str(new.id)]

        foreign = await client.patch(f"{URL}/{theirs.id}", json={"read": True})
        assert foreign.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"

        assert (await client.post(f"{URL}/read-all")).json() == {"updated": 1}
        assert (await client.get(URL)).json()["unread_count"] == 0
        again = await client.patch(f"{URL}/{new.id}", json={"read": False})
        assert again.json()["read"] is False
    finally:
        await db_session.execute(delete(User).where(User.id == other.id))
        await db_session.commit()


class DoneAI:
    async def run_job(self, job_id, job_type, payload):  # type: ignore[no-untyped-def]
        return {"job_id": job_id, "job_type": job_type, "result": {}}


@pytest.mark.db
async def test_finished_job_notifies_the_student(db_session, student_in_db):
    job = await jobs.create_job(db_session, JobType.GENERATE_NOTES, {}, requested_by=STUDENT.id)
    try:
        await jobs.run_job_inline(db_session, job, DoneAI())  # type: ignore[arg-type]
        rows = (
            await db_session.execute(select(Notification).where(Notification.user_id == STUDENT.id))
        ).scalars()
        [row] = [r for r in rows if r.data.get("job_id") == str(job.id)]
        assert (row.type, row.title) == (NotificationType.JOB_DONE, "Your notes are ready")
    finally:
        await db_session.execute(delete(AIJob).where(AIJob.id == job.id))
        await db_session.commit()


@pytest.mark.db
async def test_a_reply_notifies_the_posts_author(db_session, student_in_db):
    group = CommunityGroup(name=f"Notif {uuid.uuid4().hex[:6]}", slug=f"notif-{uuid.uuid4().hex}")
    db_session.add(group)
    await db_session.flush()
    post = Post(group_id=group.id, author_id=STUDENT.id, title="Why ATP?", body="?",
                moderation_status=ModerationStatus.APPROVED)  # fmt: skip
    db_session.add(post)
    await db_session.commit()
    try:
        job = AIJob(job_type=JobType.SUGGEST_ANSWER, status=JobStatus.SUCCEEDED,
                    input={"post_id": str(post.id)},
                    result={"result": {"body": "ATP is the energy currency."}})  # fmt: skip
        await community_service.on_answer_suggested(db_session, job)
        await db_session.commit()
        [row] = (
            await db_session.execute(
                select(Notification).where(
                    Notification.user_id == STUDENT.id,
                    Notification.type == NotificationType.COMMUNITY_REPLY,
                )
            )
        ).scalars()
        assert row.title == "BrAInBox AI answered your question"
        assert row.data["post_id"] == str(post.id) and row.data["ai_generated"] is True
    finally:
        await db_session.execute(delete(Reply).where(Reply.post_id == post.id))
        await db_session.execute(delete(Post).where(Post.id == post.id))
        await db_session.execute(delete(CommunityGroup).where(CommunityGroup.id == group.id))
        await db_session.commit()
