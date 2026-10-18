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


# TODO(Keshomigha): list_units / list_topics(unit_id) / get_topic(topic_id)
