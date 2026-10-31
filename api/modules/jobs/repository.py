"""All SQL queries for the jobs module. Owner: shared.

Tables: ai_jobs
Only this module's `service.py` may import this file.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AIJob


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> AIJob | None:
    return await session.get(AIJob, job_id)
