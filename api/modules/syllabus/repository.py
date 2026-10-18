"""All SQL queries for the syllabus module. Owner: Keshomigha.

Tables: units, topics, concepts
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Unit


async def count_units(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Unit))
    return result.scalar_one()


# TODO(Keshomigha): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> Unit | None:
#       return await session.get(Unit, id)
