"""Business logic for the syllabus module. Owner: Keshomigha.

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
from api.modules.syllabus.schemas import ModuleStatus

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


# TODO(Keshomigha): list_units / list_topics(unit_id) / get_topic(topic_id)
