"""Business logic for the syllabus module. Owner: Keshomigha.

Student syllabus tree (read-only): units -> topics -> concepts. Lists show the CURRENT
syllabus only (`is_outdated` rows are hidden). A single topic can still be opened by id when
it is outdated, because old notes and questions link to it; the response says so.

Learn navigation (Samni): subject -> units -> topics -> sub-topics, with the current student's
progress from `user_topic_progress`:
    * topic: status / score / is_weak from the student's row (no row = not started, 0, False)
    * unit:  progressPct = average topic score (topics without a row count as 0),
             status = not_started (no activity in any topic), otherwise
             strong (>= 75) | improving (40..74) | weak (< 40)

Progress is only READ here. performance.service writes it (performance imports this module, so
this module must not import performance).

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
from api.core.security import CurrentUser
from api.modules.syllabus import repository
from api.modules.syllabus.schemas import (
    AdminConceptOut,
    AdminTopicOut,
    AdminUnitOut,
    ConceptCreate,
    ConceptUpdate,
    LearnUnitOut,
    SubtopicOut,
    TopicCreate,
    TopicDetailOut,
    TopicOut,
    TopicUpdate,
    UnitCreate,
    UnitOut,
    UnitStatus,
    UnitTopicsOut,
    UnitTopicsSummary,
    UnitUpdate,
)
from shared.db.models import Concept, Topic, Unit, UserTopicProgress
from shared.enums import TopicProgressStatus

STRONG_FROM = 75  # unit average >= 75 -> "strong"
IMPROVING_FROM = 40  # unit average 40..74 -> "improving", below -> "weak"


@dataclass
class TopicInfo:
    """A topic plus its unit, for other modules (e.g. exams)."""

    id: uuid.UUID
    title: str
    unit_id: uuid.UUID
    unit_title: str
    unit_number: int = 0  # e.g. 6 for Unit 6 (added for visuals: "unit_code")
    code: str | None = None  # public code, e.g. "bio-6.1" (set by resolve_topic)


async def resolve_topic(session: AsyncSession, topic_ref: str) -> TopicInfo:
    """A topic by its public code or UUID, outdated ones included. 404 TOPIC_NOT_FOUND."""
    row = await repository.get_topic_with_unit(session, parse_ref(topic_ref))
    if row is None:
        raise NotFoundError(f"Topic '{topic_ref}' not found", code="TOPIC_NOT_FOUND")
    topic, unit = row
    return TopicInfo(topic.id, topic.title, unit.id, unit.title, unit.number, topic.code)


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


# --------------------------------------------------------------------------- pure helpers


def parse_ref(value: str) -> repository.Ref:
    """A path parameter is either a UUID or a public code ("u6", "bio-6.1")."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return value


def unit_status(progress_pct: int, started: bool) -> UnitStatus:
    """`started` = the student has activity in at least one topic of the unit."""
    if not started:
        return "not_started"
    if progress_pct >= STRONG_FROM:
        return "strong"
    if progress_pct >= IMPROVING_FROM:
        return "improving"
    return "weak"


def unit_out(unit: Unit, topic_count: int, average_score: float, started: bool) -> LearnUnitOut:
    progress_pct = round(average_score)
    return LearnUnitOut(
        id=unit.code or str(unit.id),
        uuid=unit.id,
        number=unit.number,
        title=unit.title,
        periods=unit.periods,
        icon=unit.icon,
        topic_count=topic_count,
        progress_pct=progress_pct,
        status=unit_status(progress_pct, started),
    )


def topic_out(
    topic: Topic, progress: UserTopicProgress | None, concepts: list[Concept]
) -> TopicOut:
    return TopicOut(
        id=topic.code or str(topic.id),
        uuid=topic.id,
        code=topic.number,
        title=topic.title,
        order=topic.order_index,
        status=progress.status if progress else TopicProgressStatus.NOT_STARTED,
        progress_pct=progress.score if progress else 0,
        is_weak=progress.is_weak if progress else False,
        subtopics=[SubtopicOut(id=c.code or str(c.id), title=c.name) for c in concepts],
    )


def summarise_topics(topics: list[TopicOut]) -> UnitTopicsSummary:
    return UnitTopicsSummary(
        mastered=sum(1 for t in topics if t.status == TopicProgressStatus.MASTERED),
        weak=sum(1 for t in topics if t.is_weak),
    )


def _group_by_topic(concepts: list[Concept]) -> dict[uuid.UUID, list[Concept]]:
    grouped: dict[uuid.UUID, list[Concept]] = {}
    for concept in concepts:
        grouped.setdefault(concept.topic_id, []).append(concept)
    return grouped


# --------------------------------------------------------------------------- endpoints


async def list_subject_units(
    session: AsyncSession, user: CurrentUser, subject_ref: str
) -> list[LearnUnitOut]:
    """Units of a subject with the student's progress. 404 SUBJECT_NOT_FOUND."""
    subject = await repository.get_subject(session, parse_ref(subject_ref))
    if subject is None:
        raise NotFoundError(f"Subject '{subject_ref}' not found", code="SUBJECT_NOT_FOUND")
    rows = await repository.list_units_with_scores(session, subject.id, user.id)
    return [
        unit_out(unit, count, average, started_count > 0)
        for unit, count, average, started_count in rows
    ]


async def list_unit_topics(
    session: AsyncSession, user: CurrentUser, unit_ref: str
) -> UnitTopicsOut:
    """Topics of a unit (with sub-topics and the student's progress). 404 UNIT_NOT_FOUND."""
    unit = await repository.get_unit(session, parse_ref(unit_ref))
    if unit is None or unit.is_outdated:
        raise NotFoundError(f"Unit '{unit_ref}' not found", code="UNIT_NOT_FOUND")
    rows = await repository.list_topics_with_progress(session, unit.id, user.id)
    concepts = _group_by_topic(await repository.list_concepts(session, [t.id for t, _ in rows]))
    topics = [topic_out(topic, progress, concepts.get(topic.id, [])) for topic, progress in rows]

    average = sum(t.progress_pct for t in topics) / len(topics) if topics else 0.0
    started = any(t.status != TopicProgressStatus.NOT_STARTED for t in topics)
    return UnitTopicsOut(
        unit=unit_out(unit, len(topics), average, started),
        summary=summarise_topics(topics),
        topics=topics,
    )


async def get_topic(session: AsyncSession, user: CurrentUser, topic_ref: str) -> TopicDetailOut:
    """One topic with its sub-topics and the student's progress. 404 TOPIC_NOT_FOUND."""
    row = await repository.get_topic_with_unit(session, parse_ref(topic_ref))
    if row is None:
        raise NotFoundError(f"Topic '{topic_ref}' not found", code="TOPIC_NOT_FOUND")
    topic, unit = row
    progress = await repository.get_progress(session, topic.id, user.id)
    concepts = await repository.list_concepts(session, [topic.id])
    return TopicDetailOut(
        **topic_out(topic, progress, concepts).model_dump(),
        is_outdated=topic.is_outdated,
        unit_id=unit.code or str(unit.id),
        unit_number=unit.number,
        unit_title=unit.title,
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
