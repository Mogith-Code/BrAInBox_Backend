"""Business logic for the notifications module. Owner: Mogith.

The notification center of the student app (Figma F4). Other modules create notifications by
calling `notify(...)` (through this service, never the repository). It only adds the row, so it is
saved in the caller's own commit, together with the thing it is about.

Created today:
  * JOB_DONE         a background AI job the student started finished (or failed): summaries,
                     notes, visuals, answer marking. `on_job_finished` is a listener in
                     api/core/jobs.py (`jobs.register_job_listener`).
  * PLAN_READY       a new weekly study plan (recommendations module).
  * COMMUNITY_REPLY  someone (or the AI) replied to the student's post (community module).
  * SYSTEM           moderation warnings (written by the community module itself).

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service, never its repository.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock, jobs
from api.core.errors import NotFoundError
from api.modules.notifications import repository
from api.modules.notifications.schemas import (
    NotificationKind,
    NotificationList,
    NotificationOut,
    NotificationUpdate,
    ReadAllOut,
)
from shared.db.models import AIJob, Notification
from shared.enums import JobStatus, JobType, NotificationType

MODULE_NAME = "notifications"
MAX_TITLE = 120

# Backend event -> the app's NotificationKind (icon + filter chip).
KIND_OF: dict[NotificationType, NotificationKind] = {
    NotificationType.STUDY_REMINDER: "reminder",
    NotificationType.PLAN_READY: "reminder",
    NotificationType.JOB_DONE: "recommendation",
    NotificationType.COMMUNITY_REPLY: "community",
    NotificationType.CONTENT_APPROVED: "other",
    NotificationType.SYSTEM: "other",
}

# Background jobs a student starts and then leaves: (title when done, title when it failed,
# screen to open). Other jobs don't notify: admin jobs, papers the app waits for, the OCR step
# before marking, and AI forum answers (those notify as a community reply).
JOB_MESSAGES: dict[JobType, tuple[str, str, str]] = {
    JobType.SUMMARIZE_UPLOAD: (
        "Your summary is ready",
        "We couldn't summarise your file",
        "upload",
    ),
    JobType.LEARN_UPLOAD_SUMMARY: (
        "Your summary is ready",
        "We couldn't summarise your file",
        "upload",
    ),
    JobType.GENERATE_NOTES: ("Your notes are ready", "We couldn't make your notes", "notes"),
    JobType.GENERATE_SHORT_NOTES: (
        "Your short notes are ready",
        "We couldn't make your short notes",
        "notes",
    ),
    JobType.GENERATE_VISUAL: ("Your visual is ready", "We couldn't make your visual", "visual"),
    JobType.EVALUATE_ANSWER: (
        "Your answer has been marked",
        "We couldn't mark your answer",
        "answer",
    ),
}


def notify(
    session: AsyncSession,
    user_id: uuid.UUID,
    kind: NotificationType,
    title: str,
    body: str = "",
    data: dict[str, Any] | None = None,
    *,
    ai_generated: bool = False,
) -> Notification:
    """Add an in-app notification. No commit: it is saved with the caller's commit."""
    payload = dict(data or {})
    if ai_generated:
        payload["ai_generated"] = True
    row = Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        type=kind,
        title=" ".join(title.split())[:MAX_TITLE],
        body=body.strip(),
        data=payload,
    )
    repository.add(session, row)
    return row


def preview(text: str, limit: int = 90) -> str:
    """One line of a post / reply for a notification body."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def notification_out(row: Notification) -> NotificationOut:
    data = dict(row.data or {})
    return NotificationOut(
        id=row.id,
        type=KIND_OF.get(row.type, "other"),
        event=row.type,
        title=row.title,
        body=row.body,
        created_at=row.created_at,
        read=row.read_at is not None,
        ai_generated=bool(data.pop("ai_generated", False)),
        data=data,
    )


# --------------------------------------------------------------------------- the app's routes
async def list_notifications(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int = 50, unread_only: bool = False
) -> NotificationList:
    rows = await repository.list_for_user(session, user_id, limit=limit, unread_only=unread_only)
    return NotificationList(
        items=[notification_out(r) for r in rows],
        unread_count=await repository.count_unread(session, user_id),
    )


async def update_notification(
    session: AsyncSession, user_id: uuid.UUID, notification_id: uuid.UUID, req: NotificationUpdate
) -> NotificationOut:
    """404 NOTIFICATION_NOT_FOUND (unknown, or someone else's)."""
    row = await repository.get_for_user(session, user_id, notification_id)
    if row is None:
        raise NotFoundError("Notification not found", code="NOTIFICATION_NOT_FOUND")
    if req.read and row.read_at is None:
        row.read_at = clock.now()
    elif not req.read:
        row.read_at = None
    await session.commit()
    return notification_out(row)


async def mark_all_read(session: AsyncSession, user_id: uuid.UUID) -> ReadAllOut:
    updated = await repository.mark_all_read(session, user_id, clock.now())
    await session.commit()
    return ReadAllOut(updated=updated)


# --------------------------------------------------------------------------- job finished
async def on_job_finished(session: AsyncSession, job: AIJob) -> None:
    """Listener for api/core/jobs.py: runs when any job ends, before its final commit."""
    message = JOB_MESSAGES.get(job.job_type)
    if message is None or job.requested_by is None:
        return
    if job.status not in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        return
    done_title, failed_title, screen = message
    succeeded = job.status == JobStatus.SUCCEEDED
    notify(
        session,
        job.requested_by,
        NotificationType.JOB_DONE,
        done_title if succeeded else failed_title,
        "Tap to open it." if succeeded else "Please try again.",
        {
            "screen": screen,
            "job_id": str(job.id),
            "job_type": job.job_type.value,
            "status": job.status.value,
        },
        ai_generated=succeeded,
    )


jobs.register_job_listener(on_job_finished)
