"""All SQL queries for the profiles module. Owner: Mogith.

Tables: student_profiles
Only this module's `service.py` may import this file.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import StudentProfile


async def count_student_profiles(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(StudentProfile))
    return result.scalar_one()


async def get_by_user_id(session: AsyncSession, user_id: uuid.UUID) -> StudentProfile | None:
    result = await session.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
    return result.scalar_one_or_none()


# TODO(Mogith): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> StudentProfile | None:
#       return await session.get(StudentProfile, id)


async def most_common_exam_year(session: AsyncSession, from_year: int) -> int | None:
    """The exam year most students chose (this year or later) - the admin dashboard batch."""
    result = await session.execute(
        select(StudentProfile.exam_year)
        .where(StudentProfile.exam_year >= from_year)
        .group_by(StudentProfile.exam_year)
        .order_by(func.count().desc(), StudentProfile.exam_year)
        .limit(1)
    )
    return result.scalar_one_or_none()
