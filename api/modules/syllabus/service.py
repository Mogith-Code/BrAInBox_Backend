"""Business logic for the syllabus module. Owner: Keshomigha.

Student syllabus tree (read-only): units -> topics -> concepts. Lists show the CURRENT
syllabus only (`is_outdated` rows are hidden). A single topic can still be opened by id when
it is outdated, because old notes and questions link to it; the response says so.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.errors import NotFoundError
from api.modules.syllabus import repository
from api.modules.syllabus.schemas import (
    ConceptOut,
    ModuleStatus,
    TopicDetailOut,
    TopicOut,
    UnitOut,
    UnitRef,
    UnitTopicsOut,
)
from shared.db.models import Unit

MODULE_NAME = "syllabus"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


@dataclass
class TopicInfo:
    """A topic plus its unit, for other modules (e.g. exams)."""

    id: uuid.UUID
    title: str
    unit_id: uuid.UUID
    unit_title: str


async def get_topics(session: AsyncSession, topic_ids: list[uuid.UUID]) -> list[TopicInfo]:
    """Topics in the same order as `topic_ids`. Raises NotFoundError if any id is unknown."""
    rows = await repository.get_topics_with_units(session, topic_ids)
    found = {
        topic.id: TopicInfo(topic.id, topic.title, unit.id, unit.title) for topic, unit in rows
    }
    missing = [str(i) for i in topic_ids if i not in found]
    if missing:
        raise NotFoundError(f"Unknown topic id(s): {', '.join(missing)}", code="TOPIC_NOT_FOUND")
    return [found[i] for i in topic_ids]


@dataclass
class UnitInfo:
    id: uuid.UUID
    number: int
    title: str
    exam_weight: float  # past-paper weight (1.0 until real weights are entered)

    @property
    def code(self) -> str:
        """What the app shows, e.g. "6" for Unit 6."""
        return str(self.number)


@dataclass
class TopicBrief:
    id: uuid.UUID
    unit_id: uuid.UUID
    number: str
    title: str


async def list_units(session: AsyncSession) -> list[UnitInfo]:
    """All units, Unit 1 first."""
    return [
        UnitInfo(u.id, u.number, u.title, float(u.exam_weight or 1.0))
        for u in await repository.list_units(session)
    ]


async def list_topics_by_unit(
    session: AsyncSession, unit_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[TopicBrief]]:
    """Current (not outdated) topics of each unit, in syllabus order."""
    by_unit: dict[uuid.UUID, list[TopicBrief]] = {u: [] for u in unit_ids}
    for t in await repository.list_current_topics(session, unit_ids):
        by_unit[t.unit_id].append(TopicBrief(t.id, t.unit_id, t.number, t.title))
    return by_unit


# =========================================================================== student endpoints


def _unit_out(unit: Unit, topic_count: int) -> UnitOut:
    return UnitOut(
        id=unit.id,
        number=unit.number,
        title=unit.title,
        description=unit.description,
        topic_count=topic_count,
    )


async def get_units(session: AsyncSession) -> list[UnitOut]:
    """GET /units: the current units, Unit 1 first."""
    rows = await repository.list_current_units_with_topic_counts(session)
    return [_unit_out(unit, count) for unit, count in rows]


async def get_unit_topics(session: AsyncSession, unit_id: uuid.UUID) -> UnitTopicsOut:
    """GET /units/{id}/topics: the unit and its current topics. Outdated units are not found."""
    unit = await repository.get_unit(session, unit_id)
    if unit is None or unit.is_outdated:
        raise NotFoundError("Unit not found", code="UNIT_NOT_FOUND")
    rows = await repository.list_current_topics_with_concept_counts(session, unit_id)
    topics = [
        TopicOut(
            id=topic.id,
            number=topic.number,
            title=topic.title,
            description=topic.description,
            concept_count=count,
        )
        for topic, count in rows
    ]
    return UnitTopicsOut(unit=_unit_out(unit, len(topics)), topics=topics)


async def get_topic_detail(session: AsyncSession, topic_id: uuid.UUID) -> TopicDetailOut:
    """GET /topics/{id}: one topic with its unit and current concepts."""
    found = await repository.get_topic_with_unit(session, topic_id)
    if found is None:
        raise NotFoundError("Topic not found", code="TOPIC_NOT_FOUND")
    topic, unit = found
    concepts = await repository.list_current_concepts(session, topic_id)
    return TopicDetailOut(
        id=topic.id,
        number=topic.number,
        title=topic.title,
        description=topic.description,
        is_outdated=topic.is_outdated,
        unit=UnitRef(id=unit.id, number=unit.number, title=unit.title),
        concepts=[
            ConceptOut(
                id=c.id,
                code=c.code,
                name=c.name,
                description=c.description,
                learning_outcome=c.learning_outcome,
            )
            for c in concepts
        ],
    )
