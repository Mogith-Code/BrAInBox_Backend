"""All SQL queries for the content module. Owner: Samni.

Tables: notes, uploads, summaries, library_items
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Note


async def count_notes(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Note))
    return result.scalar_one()


# TODO(Samni): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> Note | None:
#       return await session.get(Note, id)
