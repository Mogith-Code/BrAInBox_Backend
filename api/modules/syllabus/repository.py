"""All SQL queries for the syllabus module. Owner: Keshomigha.

Tables: subjects, units, topics, concepts (+ user_topic_progress, read for the Learn screens)
Only this module's `service.py` may import this file.

Functions that take a `ref` accept the UUID id or the public code ("biology", "u6", "bio-6.1").
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

<<<<<<< Updated upstream
from shared.db.models import Concept, Topic, Unit
=======
from shared.db.models import Concept, Subject, Topic, Unit, UserTopicProgress

Ref = uuid.UUID | str


def _match(id_column: Any, code_column: Any, ref: Ref) -> ColumnElement[bool]:
    """WHERE clause for a UUID id or a public code."""
    return id_column == ref if isinstance(ref, uuid.UUID) else code_column == ref


async def count_units(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Unit))
    return result.scalar_one()
>>>>>>> Stashed changes


async def get_topics_with_units(
    session: AsyncSession, topic_ids: list[uuid.UUID]
) -> list[tuple[Topic, Unit]]:
    """Topics (with their unit) for the given ids. Missing ids are simply not returned."""
    result = await session.execute(
        select(Topic, Unit).join(Unit, Unit.id == Topic.unit_id).where(Topic.id.in_(topic_ids))
    )
    return [(topic, unit) for topic, unit in result.all()]


<<<<<<< Updated upstream
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
=======
async def get_subject(session: AsyncSession, ref: Ref) -> Subject | None:
    result = await session.execute(select(Subject).where(_match(Subject.id, Subject.code, ref)))
    return result.scalar_one_or_none()


async def get_unit(session: AsyncSession, ref: Ref) -> Unit | None:
    result = await session.execute(select(Unit).where(_match(Unit.id, Unit.code, ref)))
    return result.scalar_one_or_none()


async def get_topic_with_unit(session: AsyncSession, ref: Ref) -> tuple[Topic, Unit] | None:
    result = await session.execute(
        select(Topic, Unit)
        .join(Unit, Unit.id == Topic.unit_id)
        .where(_match(Topic.id, Topic.code, ref))
    )
    row = result.one_or_none()
    return (row[0], row[1]) if row else None


async def list_units_with_scores(
    session: AsyncSession, subject_id: uuid.UUID, user_id: uuid.UUID
) -> list[tuple[Unit, int, float]]:
    """(unit, number of topics, average topic score of the user) per unit, by unit number.

    A topic the user has no progress row for counts as score 0.
    """
    result = await session.execute(
        select(
            Unit,
            func.count(Topic.id),
            func.coalesce(func.avg(func.coalesce(UserTopicProgress.score, 0)), 0),
        )
        .outerjoin(Topic, Topic.unit_id == Unit.id)
        .outerjoin(
            UserTopicProgress,
            (UserTopicProgress.topic_id == Topic.id) & (UserTopicProgress.user_id == user_id),
        )
        .where(Unit.subject_id == subject_id)
        .group_by(Unit.id)
        .order_by(Unit.number)
    )
    return [(unit, count, float(avg)) for unit, count, avg in result.all()]


async def list_topics_with_progress(
    session: AsyncSession, unit_id: uuid.UUID, user_id: uuid.UUID
) -> list[tuple[Topic, UserTopicProgress | None]]:
    """Topics of a unit in display order, each with the user's progress row (or None)."""
    result = await session.execute(
        select(Topic, UserTopicProgress)
        .outerjoin(
            UserTopicProgress,
            (UserTopicProgress.topic_id == Topic.id) & (UserTopicProgress.user_id == user_id),
        )
        .where(Topic.unit_id == unit_id)
        .order_by(Topic.order_index, Topic.number)
    )
    return [(topic, progress) for topic, progress in result.all()]


async def get_progress(
    session: AsyncSession, topic_id: uuid.UUID, user_id: uuid.UUID
) -> UserTopicProgress | None:
    result = await session.execute(
        select(UserTopicProgress).where(
            UserTopicProgress.topic_id == topic_id, UserTopicProgress.user_id == user_id
        )
>>>>>>> Stashed changes
    )
    return result.scalar_one_or_none()


<<<<<<< Updated upstream
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
=======
async def list_concepts(session: AsyncSession, topic_ids: list[uuid.UUID]) -> list[Concept]:
    """Concepts (sub-topics) of the given topics, in display order."""
    if not topic_ids:
        return []
    result = await session.execute(
        select(Concept)
        .where(Concept.topic_id.in_(topic_ids))
        .order_by(Concept.topic_id, Concept.order_index, Concept.name)
    )
    return list(result.scalars())
>>>>>>> Stashed changes
