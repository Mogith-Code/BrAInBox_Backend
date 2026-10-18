"""All SQL queries for the questions module. Owner: Udith.

Tables: questions, mcq_options, misconceptions, question_concepts
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Question


async def count_questions(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Question))
    return result.scalar_one()


# TODO(Udith): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> Question | None:
#       return await session.get(Question, id)
