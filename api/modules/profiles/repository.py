"""All SQL queries for the profiles module. Owner: Mogith.

Tables: student_profiles
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import StudentProfile


async def count_student_profiles(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(StudentProfile))
    return result.scalar_one()


# TODO(Mogith): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> StudentProfile | None:
#       return await session.get(StudentProfile, id)
