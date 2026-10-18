"""All SQL queries for the recommendations module. Owner: Udith.

Tables: resources, recommendations, study_plans, plan_items
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Recommendation


async def count_resources(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Recommendation))
    return result.scalar_one()


# TODO(Udith): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> Recommendation | None:
#       return await session.get(Recommendation, id)
