"""All SQL queries for the evaluation module.

Tables: evaluations. Read-only: questions, model_answers, topics, units, ai_jobs.
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AIJob, Evaluation, ModelAnswer, Question, Topic, Unit
from shared.enums import ContentStatus, JobStatus, QuestionType

WRITTEN_TYPES = (QuestionType.STRUCTURED, QuestionType.ESSAY)


async def count_evaluations(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Evaluation))
    return result.scalar_one()


def _written_questions(
    question_type: str | None,
    unit_id: uuid.UUID | None,
    topic_id: uuid.UUID | None,
    year: int | None,
    hide_outdated: bool,
) -> Any:
    """Approved structured / essay questions that have an approved model answer."""
    has_scheme = (
        select(ModelAnswer.id)
        .where(ModelAnswer.question_id == Question.id, ModelAnswer.status == ContentStatus.APPROVED)
        .exists()
    )
    stmt = (
        select(Question, Topic.title.label("topic_title"), Unit.number.label("unit_number"))
        .outerjoin(Topic, Topic.id == Question.topic_id)
        .outerjoin(Unit, Unit.id == Topic.unit_id)
        .where(
            Question.status == ContentStatus.APPROVED,
            Question.question_type.in_(WRITTEN_TYPES),
            has_scheme,
        )
    )
    if question_type is not None:
        stmt = stmt.where(Question.question_type == question_type)
    if unit_id is not None:
        stmt = stmt.where(Topic.unit_id == unit_id)
    if topic_id is not None:
        stmt = stmt.where(Question.topic_id == topic_id)
    if year is not None:
        stmt = stmt.where(Question.year == year)
    if hide_outdated:
        stmt = stmt.where(Question.is_outdated.is_(False))
    return stmt


async def list_written_questions(
    session: AsyncSession,
    *,
    question_type: str | None,
    unit_id: uuid.UUID | None,
    topic_id: uuid.UUID | None,
    year: int | None,
    hide_outdated: bool,
    offset: int,
    limit: int,
) -> tuple[list[Any], int]:
    stmt = _written_questions(question_type, unit_id, topic_id, year, hide_outdated)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(Question.year.desc().nulls_last(), Question.number)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return list(rows), int(total)


async def my_question_stats(
    session: AsyncSession, user_id: uuid.UUID, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, float | None]]:
    """{question_id: (my marked attempts, my best estimated marks)}."""
    if not question_ids:
        return {}
    result = await session.execute(
        select(Evaluation.question_id, func.count(), func.max(Evaluation.estimated_marks))
        .where(
            Evaluation.user_id == user_id,
            Evaluation.question_id.in_(question_ids),
            Evaluation.status == JobStatus.SUCCEEDED,
            Evaluation.estimated_marks.is_not(None),
        )
        .group_by(Evaluation.question_id)
    )
    return {qid: (int(n), best) for qid, n, best in result.all()}


async def get_question(session: AsyncSession, question_id: uuid.UUID) -> Question | None:
    return await session.get(Question, question_id)


async def get_questions(
    session: AsyncSession, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Question]:
    if not question_ids:
        return {}
    result = await session.execute(select(Question).where(Question.id.in_(question_ids)))
    return {q.id: q for q in result.scalars()}


async def add(session: AsyncSession, evaluation: Evaluation) -> None:
    session.add(evaluation)
    await session.flush()


async def get_evaluation(session: AsyncSession, evaluation_id: uuid.UUID) -> Evaluation | None:
    return await session.get(Evaluation, evaluation_id)


async def get_job(session: AsyncSession, job_id: uuid.UUID | None) -> AIJob | None:
    return await session.get(AIJob, job_id) if job_id else None


async def list_evaluations(
    session: AsyncSession,
    user_id: uuid.UUID,
    question_id: uuid.UUID | None,
    offset: int,
    limit: int,
) -> tuple[list[Evaluation], int]:
    where = [Evaluation.user_id == user_id]
    if question_id is not None:
        where.append(Evaluation.question_id == question_id)
    total = (
        await session.execute(select(func.count()).select_from(Evaluation).where(*where))
    ).scalar_one()
    rows = (
        await session.execute(
            select(Evaluation)
            .where(*where)
            .order_by(Evaluation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    return list(rows), int(total)


async def count_since(
    session: AsyncSession, user_id: uuid.UUID, since: datetime, *, handwritten: bool = False
) -> int:
    """How many evaluations this student started since `since` (for the daily limits)."""
    stmt = (
        select(func.count())
        .select_from(Evaluation)
        .where(Evaluation.user_id == user_id, Evaluation.created_at >= since)
    )
    if handwritten:
        stmt = stmt.where(Evaluation.answer_image_path.is_not(None))
    return int((await session.execute(stmt)).scalar_one())


async def list_marked(
    session: AsyncSession, *, only_manual: bool, offset: int, limit: int
) -> tuple[list[Evaluation], int]:
    """Marked evaluations for the admin accuracy screen, newest first."""
    where = [Evaluation.status == JobStatus.SUCCEEDED, Evaluation.estimated_marks.is_not(None)]
    if only_manual:
        where.append(Evaluation.manual_marks.is_not(None))
    total = (
        await session.execute(select(func.count()).select_from(Evaluation).where(*where))
    ).scalar_one()
    rows = (
        await session.execute(
            select(Evaluation)
            .where(*where)
            .order_by(Evaluation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars()
    return list(rows), int(total)


async def manual_pairs(session: AsyncSession) -> list[tuple[float, float]]:
    """[(estimated, manual)] for every manually marked evaluation."""
    result = await session.execute(
        select(Evaluation.estimated_marks, Evaluation.manual_marks).where(
            Evaluation.manual_marks.is_not(None), Evaluation.estimated_marks.is_not(None)
        )
    )
    return [(float(e), float(m)) for e, m in result.all()]


async def count_open_for_responses(
    session: AsyncSession, response_ids: list[uuid.UUID], exclude_id: uuid.UUID | None
) -> int:
    """Evaluations of these responses that are still queued / running."""
    if not response_ids:
        return 0
    stmt = (
        select(func.count())
        .select_from(Evaluation)
        .where(
            Evaluation.response_id.in_(response_ids),
            Evaluation.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(Evaluation.id != exclude_id)
    return int(await session.scalar(stmt) or 0)


# ---------------------------------------------------------------- account delete / export


async def list_user_evaluations(session: AsyncSession, user_id: uuid.UUID) -> list[Evaluation]:
    """Every evaluation of one student, oldest first (for the data export)."""
    rows = await session.scalars(
        select(Evaluation).where(Evaluation.user_id == user_id).order_by(Evaluation.created_at)
    )
    return list(rows)


async def delete_user_evaluations(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Delete every evaluation of one student. No commit."""
    await session.execute(delete(Evaluation).where(Evaluation.user_id == user_id))
