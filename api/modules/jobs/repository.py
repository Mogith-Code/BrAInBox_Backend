"""All SQL queries for the jobs module. Owner: shared.

Tables: ai_jobs
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AIJob


async def count_ai_jobs(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(AIJob))
    return result.scalar_one()


# TODO(shared): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> AIJob | None:
#       return await session.get(AIJob, id)
