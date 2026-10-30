"""All SQL queries for the performance module. Owner: Keshomigha.

Tables: mistakes, concept_mastery, unit_mastery, study_activity
Read-only for topic insights: attempts, responses, questions, mcq_options, topics, units,
misconceptions, model_answers, resources.
Only this module's `service.py` may import this file.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    Attempt,
    MCQOption,
    Misconception,
    Mistake,
    ModelAnswer,
    Question,
    Resource,
    Response,
    StudyActivity,
    Topic,
    Unit,
    UnitMastery,
)
from shared.enums import ContentStatus, QuestionType

# Attempts in these states have been marked, so their responses can be analysed.
FINISHED_ATTEMPT_STATUSES = ("submitted", "graded")


async def count_mistakes(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Mistake))
    return result.scalar_one()


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
