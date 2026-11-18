"""All SQL queries for the jobs module. Owner: shared.

Tables: ai_jobs
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AIJob
from shared.enums import JobStatus, JobType


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> AIJob | None:
    return await session.get(AIJob, job_id)


async def count_jobs_since(
    session: AsyncSession,
    user_id: uuid.UUID,
    job_type: JobType,
    since: datetime,
    *,
    exclude_failed: bool = True,
) -> int:
    stmt = (
        select(func.count())
        .select_from(AIJob)
        .where(AIJob.requested_by == user_id, AIJob.job_type == job_type, AIJob.created_at >= since)
    )
    if exclude_failed:
        stmt = stmt.where(AIJob.status != JobStatus.FAILED)
    return int(await session.scalar(stmt) or 0)


async def delete_user_jobs(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Delete the jobs one student started (their input can hold the student's answers).
    No commit. ai_usage_log rows stay for cost reports, without the job / user link."""
    await session.execute(delete(AIJob).where(AIJob.requested_by == user_id))
