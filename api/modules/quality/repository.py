"""All SQL queries for the quality module. Owner: Udith.

Tables: question_reviews, question_reports, question_stats
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import QuestionReport


async def count_question_reviews(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(QuestionReport))
    return result.scalar_one()


# TODO(Udith): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> QuestionReport | None:
#       return await session.get(QuestionReport, id)
