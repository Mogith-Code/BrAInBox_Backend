"""All SQL queries for the content module. Owner: Samni.

Tables: notes, uploads, summaries, library_items
(+ reading back the ai_jobs row this module created for an upload)
Only this module's `service.py` may import this file.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AIJob, Note, Summary, Upload
from shared.enums import JobStatus, JobType


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
