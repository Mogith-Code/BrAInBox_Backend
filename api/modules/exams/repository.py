"""All SQL queries for the exams module. Owner: Udith.

Tables: papers, paper_questions, attempts, responses
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Paper


async def count_papers(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Paper))
    return result.scalar_one()


# TODO(Udith): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> Paper | None:
#       return await session.get(Paper, id)
