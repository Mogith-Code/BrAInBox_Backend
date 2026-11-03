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
from typing import Any

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.errors import AppError, ConflictError, NotFoundError
from api.modules.syllabus import repository
from api.modules.syllabus.schemas import (
    AdminConceptOut,
    AdminTopicOut,
    AdminUnitOut,
    ConceptCreate,
    ConceptOut,
    ConceptUpdate,
    ModuleStatus,
    TopicCreate,
    TopicDetailOut,
    TopicOut,
    TopicUpdate,
    UnitCreate,
    UnitOut,
    UnitRef,
    UnitTopicsOut,
    UnitUpdate,
)
from shared.db.models import Concept, Topic, Unit

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
    unit_number: int = 0  # e.g. 6 for Unit 6 (added for visuals: "unit_code")


async def get_topics(session: AsyncSession, topic_ids: list[uuid.UUID]) -> list[TopicInfo]:
    """Topics in the same order as `topic_ids`. Raises NotFoundError if any id is unknown."""
    rows = await repository.get_topics_with_units(session, topic_ids)
    found = {
        topic.id: TopicInfo(topic.id, topic.title, unit.id, unit.title, unit.number)
        for topic, unit in rows
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


# =========================================================================== admin (/admin/syllabus)
# Admins see outdated rows too. Removing something students have used = mark it outdated.
#   * units are never deleted (the 10 syllabus units; deleting one would also delete the
#     students' unit-mastery history)
#   * a topic can be deleted only when it has no concepts and nothing else points at it
#   * a concept can be deleted only when no question / note / visual points at it
# TODO(Mogith): write an audit_log row for every change once admin.service.record_audit exists.

IN_USE_MESSAGE = "{what} is used by questions, notes or visuals. Mark it outdated instead."


def _apply_update(row: Any, req: BaseModel, required: tuple[str, ...]) -> set[str]:
    """Copy the fields the admin sent (PATCH) onto the row. Required fields can't be null."""
    for field in req.model_fields_set:
        value = getattr(req, field)
        if value is None and field in required:
            raise AppError(f"{field} cannot be empty", code="FIELD_REQUIRED")
        setattr(row, field, value)
    return req.model_fields_set


async def _delete_or_conflict(session: AsyncSession, row: Topic | Concept, what: str) -> None:
    try:
        await repository.delete(session, row)
    except IntegrityError as exc:  # ON DELETE RESTRICT: content still points at it
        await session.rollback()
        raise ConflictError(IN_USE_MESSAGE.format(what=what), code="IN_USE") from exc
    await session.commit()


# ---------------------------------------------------------------- units


def _admin_unit_out(unit: Unit, topic_count: int) -> AdminUnitOut:
    return AdminUnitOut(
        id=unit.id,
        number=unit.number,
        title=unit.title,
        description=unit.description,
        exam_weight=float(unit.exam_weight),
        is_outdated=unit.is_outdated,
        topic_count=topic_count,
    )


async def _admin_unit(session: AsyncSession, unit_id: uuid.UUID) -> Unit:
    unit = await repository.get_unit(session, unit_id)
    if unit is None:
        raise NotFoundError("Unit not found", code="UNIT_NOT_FOUND")
    return unit


async def _check_unit_number_free(
    session: AsyncSession, number: int, unit_id: uuid.UUID | None = None
) -> None:
    other = await repository.get_unit_by_number(session, number)
    if other is not None and other.id != unit_id:
        raise ConflictError(f"Unit {number} already exists", code="UNIT_NUMBER_TAKEN")


async def admin_list_units(session: AsyncSession) -> list[AdminUnitOut]:
    rows = await repository.list_all_units_with_topic_counts(session)
    return [_admin_unit_out(unit, count) for unit, count in rows]


async def admin_create_unit(session: AsyncSession, req: UnitCreate) -> AdminUnitOut:
    await _check_unit_number_free(session, req.number)
    unit = Unit(**req.model_dump())
    await repository.add(session, unit)
    await session.commit()
    return _admin_unit_out(unit, 0)


async def admin_update_unit(
    session: AsyncSession, unit_id: uuid.UUID, req: UnitUpdate
) -> AdminUnitOut:
    unit = await _admin_unit(session, unit_id)
    if req.number is not None:
        await _check_unit_number_free(session, req.number, unit.id)
    _apply_update(unit, req, required=("number", "title", "exam_weight", "is_outdated"))
    await session.commit()
    return _admin_unit_out(unit, await repository.count_topics(session, unit.id))


# ---------------------------------------------------------------- topics


def _admin_topic_out(topic: Topic, concept_count: int) -> AdminTopicOut:
    return AdminTopicOut(
        id=topic.id,
        unit_id=topic.unit_id,
        number=topic.number,
        title=topic.title,
        description=topic.description,
        order_index=topic.order_index,
        is_outdated=topic.is_outdated,
        concept_count=concept_count,
    )


async def _admin_topic(session: AsyncSession, topic_id: uuid.UUID) -> Topic:
    topic = await repository.get_topic(session, topic_id)
    if topic is None:
        raise NotFoundError("Topic not found", code="TOPIC_NOT_FOUND")
    return topic


async def _check_topic_number_free(
    session: AsyncSession, unit_id: uuid.UUID, number: str, topic_id: uuid.UUID | None = None
) -> None:
    other = await repository.get_topic_by_number(session, unit_id, number)
    if other is not None and other.id != topic_id:
        raise ConflictError(
            f"Topic {number} already exists in this unit", code="TOPIC_NUMBER_TAKEN"
        )


async def admin_list_topics(session: AsyncSession, unit_id: uuid.UUID) -> list[AdminTopicOut]:
    await _admin_unit(session, unit_id)
    rows = await repository.list_all_topics_with_concept_counts(session, unit_id)
    return [_admin_topic_out(topic, count) for topic, count in rows]


async def admin_create_topic(
    session: AsyncSession, unit_id: uuid.UUID, req: TopicCreate
) -> AdminTopicOut:
    await _admin_unit(session, unit_id)
    await _check_topic_number_free(session, unit_id, req.number)
    topic = Topic(unit_id=unit_id, **req.model_dump())
    await repository.add(session, topic)
    await session.commit()
    return _admin_topic_out(topic, 0)


async def admin_update_topic(
    session: AsyncSession, topic_id: uuid.UUID, req: TopicUpdate
) -> AdminTopicOut:
    topic = await _admin_topic(session, topic_id)
    if req.number is not None:
        await _check_topic_number_free(session, topic.unit_id, req.number, topic.id)
    _apply_update(topic, req, required=("number", "title", "order_index", "is_outdated"))
    await session.commit()
    return _admin_topic_out(topic, await repository.count_concepts(session, topic.id))


async def admin_delete_topic(session: AsyncSession, topic_id: uuid.UUID) -> None:
    topic = await _admin_topic(session, topic_id)
    if await repository.count_concepts(session, topic.id):
        raise ConflictError(
            "Delete or move this topic's concepts first, or mark the topic outdated.",
            code="TOPIC_HAS_CONCEPTS",
        )
    await _delete_or_conflict(session, topic, "This topic")


# ---------------------------------------------------------------- concepts

# Changing these makes the stored embedding (used to match questions to concepts) stale.
EMBEDDED_FIELDS = {"name", "description", "learning_outcome"}


def _admin_concept_out(concept: Concept) -> AdminConceptOut:
    return AdminConceptOut(
        id=concept.id,
        topic_id=concept.topic_id,
        code=concept.code,
        name=concept.name,
        description=concept.description,
        learning_outcome=concept.learning_outcome,
        order_index=concept.order_index,
        is_outdated=concept.is_outdated,
    )


async def _admin_concept(session: AsyncSession, concept_id: uuid.UUID) -> Concept:
    concept = await repository.get_concept(session, concept_id)
    if concept is None:
        raise NotFoundError("Concept not found", code="CONCEPT_NOT_FOUND")
    return concept


async def _check_concept_code_free(
    session: AsyncSession, code: str, concept_id: uuid.UUID | None = None
) -> None:
    other = await repository.get_concept_by_code(session, code)
    if other is not None and other.id != concept_id:
        raise ConflictError(f"Concept code {code} already exists", code="CONCEPT_CODE_TAKEN")


async def admin_list_concepts(session: AsyncSession, topic_id: uuid.UUID) -> list[AdminConceptOut]:
    await _admin_topic(session, topic_id)
    return [_admin_concept_out(c) for c in await repository.list_all_concepts(session, topic_id)]


async def admin_create_concept(
    session: AsyncSession, topic_id: uuid.UUID, req: ConceptCreate
) -> AdminConceptOut:
    await _admin_topic(session, topic_id)
    if req.code is not None:
        await _check_concept_code_free(session, req.code)
    concept = Concept(topic_id=topic_id, **req.model_dump())
    await repository.add(session, concept)
    await session.commit()
    return _admin_concept_out(concept)


async def admin_update_concept(
    session: AsyncSession, concept_id: uuid.UUID, req: ConceptUpdate
) -> AdminConceptOut:
    concept = await _admin_concept(session, concept_id)
    if req.code is not None:
        await _check_concept_code_free(session, req.code, concept.id)
    changed = _apply_update(concept, req, required=("name", "order_index", "is_outdated"))
    if changed & EMBEDDED_FIELDS:
        concept.embedding = None  # recomputed by the next embedding run
        concept.embedding_model = None
    await session.commit()
    return _admin_concept_out(concept)


async def admin_delete_concept(session: AsyncSession, concept_id: uuid.UUID) -> None:
    concept = await _admin_concept(session, concept_id)
    await _delete_or_conflict(session, concept, "This concept")
