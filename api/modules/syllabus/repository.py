"""All SQL queries for the syllabus module. Owner: Keshomigha.

Tables: units, topics, concepts
Only this module's `service.py` may import this file.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Topic, Unit


async def count_units(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Unit))
    return result.scalar_one()


async def get_topics_with_units(
    session: AsyncSession, topic_ids: list[uuid.UUID]
) -> list[tuple[Topic, Unit]]:
    """Topics (with their unit) for the given ids. Missing ids are simply not returned."""
    result = await session.execute(
        select(Topic, Unit).join(Unit, Unit.id == Topic.unit_id).where(Topic.id.in_(topic_ids))
    )
    return [(topic, unit) for topic, unit in result.all()]


# TODO(Keshomigha): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> Unit | None:
#       return await session.get(Unit, id)
