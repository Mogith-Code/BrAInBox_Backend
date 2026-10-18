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


async def list_units(session: AsyncSession) -> list[Unit]:
    result = await session.execute(select(Unit).order_by(Unit.number))
    return list(result.scalars())


async def list_current_topics(session: AsyncSession, unit_ids: list[uuid.UUID]) -> list[Topic]:
    """Topics of these units that are in the current syllabus (not outdated), in order."""
    result = await session.execute(
        select(Topic)
        .where(Topic.unit_id.in_(unit_ids), Topic.is_outdated.is_(False))
        .order_by(Topic.order_index, Topic.number)
    )
    return list(result.scalars())


# TODO(Keshomigha): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> Unit | None:
#       return await session.get(Unit, id)
