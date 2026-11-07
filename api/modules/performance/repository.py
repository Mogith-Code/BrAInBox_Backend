"""All SQL queries for the performance module. Owner: Keshomigha.

Tables: mistakes, concept_mastery, unit_mastery, study_activity
Read-only for topic insights: attempts, responses, questions, mcq_options, topics, units,
misconceptions, model_answers, resources.
Only this module's `service.py` may import this file.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared.db.models import (
    Attempt,
    MCQOption,
    Misconception,
    Mistake,
    ModelAnswer,
    Question,
    QuestionConcept,
    Resource,
    Response,
    StudyActivity,
    Topic,
    Unit,
    UnitMastery,
)
from shared.enums import ContentStatus, MistakeType, QuestionType

# Attempts in these states have been marked, so their responses can be analysed.
FINISHED_ATTEMPT_STATUSES = ("submitted", "graded")


async def get_attempt(session: AsyncSession, attempt_id: uuid.UUID) -> Attempt | None:
    return await session.get(Attempt, attempt_id)


@dataclass
class AnswerRow:
    """One stored MCQ response of the student, with its question's topic."""

    response_id: uuid.UUID
    attempt_id: uuid.UUID
    question_id: uuid.UUID
    question: str
    question_explanation: str | None
    topic_id: uuid.UUID | None
    topic: str | None
    topic_number: str | None
    unit: str | None
    selected_option_id: uuid.UUID | None
    option_question_id: uuid.UUID | None  # the question the selected option belongs to
    misconception_id: uuid.UUID | None  # misconception behind the selected option
    is_correct: bool | None
    created_at: datetime


async def get_mcq_answer_rows(
    session: AsyncSession, user_id: uuid.UUID, attempt_id: uuid.UUID | None = None
) -> list[AnswerRow]:
    """MCQ responses from the student's finished attempts, oldest first."""
    stmt = (
        select(
            Response.id.label("response_id"),
            Response.attempt_id,
            Response.question_id,
            Question.stem.label("question"),
            Question.explanation.label("question_explanation"),
            Question.topic_id,
            Topic.title.label("topic"),
            Topic.number.label("topic_number"),
            Unit.title.label("unit"),
            Response.selected_option_id,
            MCQOption.question_id.label("option_question_id"),
            MCQOption.misconception_id,
            Response.is_correct,
            Response.created_at,
        )
        .join(Attempt, Attempt.id == Response.attempt_id)
        .join(Question, Question.id == Response.question_id)
        .outerjoin(Topic, Topic.id == Question.topic_id)
        .outerjoin(Unit, Unit.id == Topic.unit_id)
        .outerjoin(MCQOption, MCQOption.id == Response.selected_option_id)
        .where(
            Attempt.user_id == user_id,
            Attempt.status.in_(FINISHED_ATTEMPT_STATUSES),
            Question.question_type == QuestionType.MCQ,
        )
        .order_by(Response.created_at, Response.id)
    )
    if attempt_id is not None:
        stmt = stmt.where(Response.attempt_id == attempt_id)
    rows = (await session.execute(stmt)).all()
    return [AnswerRow(**row._asdict()) for row in rows]


async def get_misconceptions(
    session: AsyncSession, misconception_ids: list[uuid.UUID]
) -> list[Misconception]:
    if not misconception_ids:
        return []
    result = await session.execute(
        select(Misconception).where(Misconception.id.in_(misconception_ids))
    )
    return list(result.scalars().all())


async def get_model_answers(
    session: AsyncSession, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Approved model answer text per question (the oldest one if there are several)."""
    if not question_ids:
        return {}
    result = await session.execute(
        select(ModelAnswer.question_id, ModelAnswer.answer_text)
        .where(
            ModelAnswer.question_id.in_(question_ids),
            ModelAnswer.status == ContentStatus.APPROVED,
        )
        .order_by(ModelAnswer.created_at)
    )
    answers: dict[uuid.UUID, str] = {}
    for question_id, text in result.all():
        answers.setdefault(question_id, text)
    return answers


async def get_topic_resources(
    session: AsyncSession, topic_ids: list[uuid.UUID], per_topic: int
) -> dict[uuid.UUID, list[Resource]]:
    """Approved learning resources linked to each topic (at most `per_topic` each)."""
    if not topic_ids:
        return {}
    result = await session.execute(
        select(Resource)
        .where(Resource.topic_id.in_(topic_ids), Resource.status == ContentStatus.APPROVED)
        .order_by(Resource.created_at)
    )
    by_topic: dict[uuid.UUID, list[Resource]] = {}
    for resource in result.scalars().all():
        if resource.topic_id is None:
            continue
        items = by_topic.setdefault(resource.topic_id, [])
        if len(items) < per_topic:
            items.append(resource)
    return by_topic


# ---------------------------------------------------------------- unit mastery (history)
async def add_unit_mastery(session: AsyncSession, rows: list[UnitMastery]) -> None:
    session.add_all(rows)
    await session.flush()


async def latest_unit_mastery(
    session: AsyncSession, user_id: uuid.UUID, before: datetime | None = None
) -> dict[uuid.UUID, int]:
    """{unit_id: mastery} from the newest snapshot per unit (optionally only older than `before`)."""
    stmt = (
        select(UnitMastery.unit_id, UnitMastery.mastery)
        .where(UnitMastery.user_id == user_id)
        # Postgres DISTINCT ON: keep the first row per unit = the newest one
        .ext(distinct_on(UnitMastery.unit_id))
        .order_by(UnitMastery.unit_id, UnitMastery.created_at.desc())
    )
    if before is not None:
        stmt = stmt.where(UnitMastery.created_at < before)
    result = await session.execute(stmt)
    return {unit_id: mastery for unit_id, mastery in result.all()}


async def latest_unit_mastery_rows(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[uuid.UUID, UnitMastery]:
    """{unit_id: newest snapshot row} - like latest_unit_mastery, plus source and date."""
    result = await session.execute(
        select(UnitMastery)
        .where(UnitMastery.user_id == user_id)
        .ext(distinct_on(UnitMastery.unit_id))
        .order_by(UnitMastery.unit_id, UnitMastery.created_at.desc())
    )
    return {row.unit_id: row for row in result.scalars()}


# ---------------------------------------------------------------- study activity (streak)
async def add_study_day(session: AsyncSession, user_id: uuid.UUID, day: date) -> None:
    """One row per student per day; a second call on the same day does nothing."""
    await session.execute(
        insert(StudyActivity)
        .values(user_id=user_id, activity_date=day)
        .on_conflict_do_nothing(constraint="uq_study_activity_user_date")
    )


async def study_days_since(session: AsyncSession, user_id: uuid.UUID, since: date) -> set[date]:
    result = await session.execute(
        select(StudyActivity.activity_date).where(
            StudyActivity.user_id == user_id, StudyActivity.activity_date >= since
        )
    )
    return set(result.scalars())


# ---------------------------------------------------------------- mistakes: recording
async def recorded_response_ids(
    session: AsyncSession, response_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of these responses already have a mistake row."""
    if not response_ids:
        return set()
    result = await session.execute(
        select(Mistake.response_id).where(Mistake.response_id.in_(response_ids))
    )
    return {response_id for response_id in result.scalars() if response_id is not None}


async def get_main_concepts(
    session: AsyncSession, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """{question_id: the concept it tests most}. Questions without a concept are left out."""
    if not question_ids:
        return {}
    result = await session.execute(
        select(QuestionConcept.question_id, QuestionConcept.concept_id)
        .where(QuestionConcept.question_id.in_(question_ids))
        .ext(distinct_on(QuestionConcept.question_id))
        # concept_id as the tie-break, so the same concept is chosen every time
        .order_by(
            QuestionConcept.question_id, QuestionConcept.weight.desc(), QuestionConcept.concept_id
        )
    )
    return {question_id: concept_id for question_id, concept_id in result.all()}


async def add_mistakes(session: AsyncSession, rows: list[Mistake]) -> None:
    session.add_all(rows)
    await session.flush()


# ---------------------------------------------------------------- mistakes: journal
@dataclass
class MistakeRow:
    """One mistake with everything the journal shows."""

    mistake: Mistake
    question: str | None
    explanation: str | None
    your_answer: str | None
    topic_id: uuid.UUID | None
    topic: str | None
    topic_number: str | None
    unit_id: uuid.UUID | None
    unit_number: int | None
    unit: str | None
    source: str | None
    misconception: Misconception | None


def _mistakes_query(user_id: uuid.UUID) -> Select[Any]:
    selected = aliased(MCQOption)
    return (
        select(
            Mistake,
            Question.stem.label("question"),
            Question.explanation.label("explanation"),
            selected.text.label("your_answer"),
            Topic.id.label("topic_id"),
            Topic.title.label("topic"),
            Topic.number.label("topic_number"),
            Unit.id.label("unit_id"),
            Unit.number.label("unit_number"),
            Unit.title.label("unit"),
            Attempt.kind.label("source"),
            Misconception,
        )
        .select_from(Mistake)
        # All outer joins: a deleted question or response must not hide the mistake.
        .outerjoin(Question, Question.id == Mistake.question_id)
        .outerjoin(Response, Response.id == Mistake.response_id)
        .outerjoin(selected, selected.id == Response.selected_option_id)
        .outerjoin(Attempt, Attempt.id == Response.attempt_id)
        .outerjoin(Topic, Topic.id == Question.topic_id)
        .outerjoin(Unit, Unit.id == func.coalesce(Topic.unit_id, Question.unit_id))
        .outerjoin(Misconception, Misconception.id == Mistake.misconception_id)
        .where(Mistake.user_id == user_id)
    )


def _mistake_row(row: Any) -> MistakeRow:
    return MistakeRow(
        mistake=row.Mistake,
        question=row.question,
        explanation=row.explanation,
        your_answer=row.your_answer,
        topic_id=row.topic_id,
        topic=row.topic,
        topic_number=row.topic_number,
        unit_id=row.unit_id,
        unit_number=row.unit_number,
        unit=row.unit,
        source=str(row.source) if row.source is not None else None,
        misconception=row.Misconception,
    )


async def list_mistakes(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    mistake_type: MistakeType | None = None,
    unit_id: uuid.UUID | None = None,
    resolved: bool | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[MistakeRow], int]:
    """One page of the student's mistakes (newest first) and the total matching the filters."""
    stmt = _mistakes_query(user_id)
    if mistake_type is not None:
        stmt = stmt.where(Mistake.mistake_type == mistake_type)
    if unit_id is not None:
        stmt = stmt.where(Unit.id == unit_id)
    if resolved is not None:
        stmt = stmt.where(
            Mistake.resolved_at.is_not(None) if resolved else Mistake.resolved_at.is_(None)
        )
    total = await session.scalar(stmt.with_only_columns(func.count(Mistake.id)))
    rows = await session.execute(
        stmt.order_by(Mistake.created_at.desc(), Mistake.id).offset(offset).limit(limit)
    )
    return [_mistake_row(row) for row in rows.all()], total or 0


async def get_mistake_row(
    session: AsyncSession, user_id: uuid.UUID, mistake_id: uuid.UUID
) -> MistakeRow | None:
    """This student's mistake, or None (also when it belongs to someone else)."""
    result = await session.execute(_mistakes_query(user_id).where(Mistake.id == mistake_id))
    row = result.first()
    return _mistake_row(row) if row else None


async def get_correct_answers(
    session: AsyncSession, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """{question_id: the correct option's text}."""
    if not question_ids:
        return {}
    result = await session.execute(
        select(MCQOption.question_id, MCQOption.text).where(
            MCQOption.question_id.in_(question_ids), MCQOption.is_correct.is_(True)
        )
    )
    return {question_id: text for question_id, text in result.all()}
