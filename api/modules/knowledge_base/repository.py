"""All SQL queries for the knowledge_base module. Owner: Keshomigha.

Tables: model_answers, answer_points, keywords
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import ModelAnswer


async def count_model_answers(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(ModelAnswer))
    return result.scalar_one()


# TODO(Keshomigha): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> ModelAnswer | None:
#       return await session.get(ModelAnswer, id)
