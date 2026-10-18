"""All SQL queries for the evaluation module. Owner: Keshomigha.

Tables: evaluations
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Evaluation


async def count_evaluations(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Evaluation))
    return result.scalar_one()


# TODO(Keshomigha): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> Evaluation | None:
#       return await session.get(Evaluation, id)
