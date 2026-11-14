"""All SQL queries for the content module. Owner: Samni.

Tables: notes, uploads, summaries, library_items
(+ reading back the ai_jobs row this module created for an upload)
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AIJob, Note, SourceDocument, Summary, Topic, Unit, Upload
from shared.enums import ContentStatus, JobStatus, JobType


async def count_notes(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Note))
    return result.scalar_one()


# ---------------------------------------------------------------- uploads + summaries
async def create_upload(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    topic_id: uuid.UUID | None,
    file_name: str,
    file_path: str,
    mime_type: str,
    size_bytes: int,
    upload_id: uuid.UUID | None = None,
) -> Upload:
    """Insert an upload with status "queued". No commit.

    Pass `upload_id` when the id is needed before the row exists (e.g. in the storage path).
    """
    upload = Upload(
        id=upload_id or uuid.uuid4(),
        user_id=user_id,
        topic_id=topic_id,
        file_name=file_name,
        file_path=file_path,
        mime_type=mime_type,
        size_bytes=size_bytes,
        processing_status=JobStatus.QUEUED,
    )
    session.add(upload)
    await session.flush()
    return upload


async def get_upload(session: AsyncSession, upload_id: uuid.UUID) -> Upload | None:
    return await session.get(Upload, upload_id)


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> AIJob | None:
    """The ai_jobs row of an upload (created and updated through api/core/jobs.py)."""
    return await session.get(AIJob, job_id)


async def get_upload_job(session: AsyncSession, upload: Upload) -> AIJob | None:
    """The newest SUMMARIZE_UPLOAD job of an upload. The job input holds the upload id."""
    result = await session.execute(
        select(AIJob)
        .where(
            AIJob.requested_by == upload.user_id,  # indexed, keeps the search small
            AIJob.job_type == JobType.SUMMARIZE_UPLOAD,
            AIJob.input["upload_id"].astext == str(upload.id),
        )
        .order_by(AIJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def save_summary(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    upload_id: uuid.UUID,
    topic_id: uuid.UUID | None,
    body_md: str,
    prompt_version: str | None,
) -> Summary:
    """Insert the summary of an upload. No commit."""
    summary = Summary(
        user_id=user_id,
        upload_id=upload_id,
        topic_id=topic_id,
        body_md=body_md,
        prompt_version=prompt_version,
    )
    session.add(summary)
    await session.flush()
    return summary


async def get_summary_for_upload(session: AsyncSession, upload_id: uuid.UUID) -> Summary | None:
    """The newest summary of an upload."""
    result = await session.execute(
        select(Summary)
        .where(Summary.upload_id == upload_id)
        .order_by(Summary.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------- admin: notes library
async def list_notes(
    session: AsyncSession,
    *,
    note_type: str | None,
    status: ContentStatus | None,
    unit_number: int | None,
    limit: int,
) -> list[tuple[Note, Topic, Unit]]:
    """Notes with their topic and unit, last changed first. No status = all but archived."""
    stmt = (
        select(Note, Topic, Unit)
        .join(Topic, Topic.id == Note.topic_id)
        .join(Unit, Unit.id == Topic.unit_id)
        .order_by(Note.updated_at.desc(), Note.id)
        .limit(limit)
    )
    if note_type is not None:
        stmt = stmt.where(Note.note_type == note_type)
    if status is not None:
        stmt = stmt.where(Note.status == status)
    else:
        stmt = stmt.where(Note.status != ContentStatus.ARCHIVED)
    if unit_number is not None:
        stmt = stmt.where(Unit.number == unit_number)
    return [(n, t, u) for n, t, u in (await session.execute(stmt)).all()]


async def get_note_with_topic(
    session: AsyncSession, note_id: uuid.UUID
) -> tuple[Note, Topic, Unit] | None:
    row = (
        await session.execute(
            select(Note, Topic, Unit)
            .join(Topic, Topic.id == Note.topic_id)
            .join(Unit, Unit.id == Topic.unit_id)
            .where(Note.id == note_id)
        )
    ).first()
    return (row[0], row[1], row[2]) if row else None


async def other_approved_notes(session: AsyncSession, note: Note) -> list[Note]:
    """Approved topic-level notes of the same topic and kind (only one may be approved)."""
    result = await session.execute(
        select(Note).where(
            Note.topic_id == note.topic_id,
            Note.note_type == note.note_type,
            Note.concept_id.is_(None),
            Note.status == ContentStatus.APPROVED,
            Note.id != note.id,
        )
    )
    return list(result.scalars())


async def pending_review_counts(session: AsyncSession, older_than: datetime) -> tuple[int, int]:
    """For the dashboard: (notes waiting for review, how many of them are older)."""
    result = await session.execute(
        select(func.count(), func.count().filter(Note.created_at < older_than)).where(
            Note.status == ContentStatus.PENDING_REVIEW
        )
    )
    total, old = result.one()
    return int(total), int(old)


async def notes_made_per_day(session: AsyncSession, since: datetime) -> dict[date, int]:
    """{Sri Lanka date: notes created} since `since` - for the dashboard chart."""
    day = func.date(func.timezone("Asia/Colombo", Note.created_at))
    result = await session.execute(
        select(day, func.count()).where(Note.created_at >= since).group_by(day)
    )
    return {d: int(n) for d, n in result.all()}


# ---------------------------------------------------------------- admin: RAG source documents
async def list_source_documents(
    session: AsyncSession, limit: int
) -> list[tuple[SourceDocument, int | None]]:
    """(document, its unit number), last changed first."""
    result = await session.execute(
        select(SourceDocument, Unit.number)
        .outerjoin(Unit, Unit.id == SourceDocument.unit_id)
        .order_by(SourceDocument.updated_at.desc(), SourceDocument.id)
        .limit(limit)
    )
    return [(d, n) for d, n in result.all()]


async def get_source_document(
    session: AsyncSession, document_id: uuid.UUID
) -> SourceDocument | None:
    return await session.get(SourceDocument, document_id)


async def add_row(session: AsyncSession, row: object) -> None:
    session.add(row)
    await session.flush()
