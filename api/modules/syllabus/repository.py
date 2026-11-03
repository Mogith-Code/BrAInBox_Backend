"""All SQL queries for the syllabus module. Owner: Keshomigha.

Tables: units, topics, concepts
Only this module's `service.py` may import this file.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Concept, Topic, Unit


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


# ---------------------------------------------------------------- student syllabus tree


async def list_current_units_with_topic_counts(session: AsyncSession) -> list[tuple[Unit, int]]:
    """Current units (Unit 1 first), each with its number of current topics."""
    topic_count = (
        select(func.count(Topic.id))
        .where(Topic.unit_id == Unit.id, Topic.is_outdated.is_(False))
        .scalar_subquery()
    )
    result = await session.execute(
        select(Unit, topic_count).where(Unit.is_outdated.is_(False)).order_by(Unit.number)
    )
    return [(unit, count) for unit, count in result.all()]


async def get_unit(session: AsyncSession, unit_id: uuid.UUID) -> Unit | None:
    return await session.get(Unit, unit_id)


async def list_current_topics_with_concept_counts(
    session: AsyncSession, unit_id: uuid.UUID
) -> list[tuple[Topic, int]]:
    """Current topics of one unit, in syllabus order, each with its number of current concepts."""
    concept_count = (
        select(func.count(Concept.id))
        .where(Concept.topic_id == Topic.id, Concept.is_outdated.is_(False))
        .scalar_subquery()
    )
    result = await session.execute(
        select(Topic, concept_count)
        .where(Topic.unit_id == unit_id, Topic.is_outdated.is_(False))
        .order_by(Topic.order_index, Topic.number)
    )
    return [(topic, count) for topic, count in result.all()]


async def get_topic_with_unit(
    session: AsyncSession, topic_id: uuid.UUID
) -> tuple[Topic, Unit] | None:
    """The topic (outdated or not) and its unit, or None."""
    result = await session.execute(
        select(Topic, Unit).join(Unit, Unit.id == Topic.unit_id).where(Topic.id == topic_id)
    )
    row = result.first()
    return (row[0], row[1]) if row else None


async def list_current_concepts(session: AsyncSession, topic_id: uuid.UUID) -> list[Concept]:
    """Current concepts of one topic, in syllabus order."""
    result = await session.execute(
        select(Concept)
        .where(Concept.topic_id == topic_id, Concept.is_outdated.is_(False))
        .order_by(Concept.order_index, Concept.code)
    )
    return list(result.scalars())


# ---------------------------------------------------------------- admin (outdated rows included)


async def list_all_units_with_topic_counts(session: AsyncSession) -> list[tuple[Unit, int]]:
    """Every unit (Unit 1 first), each with its number of topics (outdated included)."""
    topic_count = select(func.count(Topic.id)).where(Topic.unit_id == Unit.id).scalar_subquery()
    result = await session.execute(select(Unit, topic_count).order_by(Unit.number))
    return [(unit, count) for unit, count in result.all()]


async def get_unit_by_number(session: AsyncSession, number: int) -> Unit | None:
    result = await session.execute(select(Unit).where(Unit.number == number))
    return result.scalar_one_or_none()


async def count_topics(session: AsyncSession, unit_id: uuid.UUID) -> int:
    result = await session.execute(select(func.count(Topic.id)).where(Topic.unit_id == unit_id))
    return result.scalar_one()


async def list_all_topics_with_concept_counts(
    session: AsyncSession, unit_id: uuid.UUID
) -> list[tuple[Topic, int]]:
    """Every topic of one unit (syllabus order), each with its number of concepts."""
    concept_count = (
        select(func.count(Concept.id)).where(Concept.topic_id == Topic.id).scalar_subquery()
    )
    result = await session.execute(
        select(Topic, concept_count)
        .where(Topic.unit_id == unit_id)
        .order_by(Topic.order_index, Topic.number)
    )
    return [(topic, count) for topic, count in result.all()]


async def get_topic(session: AsyncSession, topic_id: uuid.UUID) -> Topic | None:
    return await session.get(Topic, topic_id)


async def get_topic_by_number(
    session: AsyncSession, unit_id: uuid.UUID, number: str
) -> Topic | None:
    result = await session.execute(
        select(Topic).where(Topic.unit_id == unit_id, Topic.number == number)
    )
    return result.scalar_one_or_none()


async def count_concepts(session: AsyncSession, topic_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count(Concept.id)).where(Concept.topic_id == topic_id)
    )
    return result.scalar_one()


async def list_all_concepts(session: AsyncSession, topic_id: uuid.UUID) -> list[Concept]:
    """Every concept of one topic (outdated included), in syllabus order."""
    result = await session.execute(
        select(Concept)
        .where(Concept.topic_id == topic_id)
        .order_by(Concept.order_index, Concept.code)
    )
    return list(result.scalars())


async def get_concept(session: AsyncSession, concept_id: uuid.UUID) -> Concept | None:
    return await session.get(Concept, concept_id)


async def get_concept_by_code(session: AsyncSession, code: str) -> Concept | None:
    result = await session.execute(select(Concept).where(Concept.code == code))
    return result.scalar_one_or_none()


async def add(session: AsyncSession, row: Unit | Topic | Concept) -> None:
    session.add(row)
    await session.flush()


async def delete(session: AsyncSession, row: Topic | Concept) -> None:
    """Raises IntegrityError when other content still points at the row (ON DELETE RESTRICT)."""
    await session.delete(row)
    await session.flush()
