"""All SQL queries for the visuals module. Owner: Mogith.

Tables: visuals, visual_reports
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Visual


async def count_visuals(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Visual))
    return result.scalar_one()


# TODO(Mogith): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> Visual | None:
#       return await session.get(Visual, id)
