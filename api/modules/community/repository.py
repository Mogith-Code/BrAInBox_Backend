"""All SQL queries for the community module. Owner: Mogith.

Tables: community_groups, group_members, posts, replies, votes, content_reports
Only this module's `service.py` may import this file.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Post


async def count_community_groups(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Post))
    return result.scalar_one()


# TODO(Mogith): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> Post | None:
#       return await session.get(Post, id)
