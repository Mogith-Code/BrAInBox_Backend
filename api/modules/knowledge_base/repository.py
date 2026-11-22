"""All SQL queries for the knowledge_base module. Owner: Keshomigha.

Tables: model_answers, answer_points, keywords
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AnswerPoint, Keyword, ModelAnswer
from shared.enums import ContentStatus


async def count_model_answers(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(ModelAnswer))
    return result.scalar_one()


async def list_model_answers(
    session: AsyncSession, question_id: uuid.UUID | None, status: str | None, limit: int
) -> list[ModelAnswer]:
    stmt = select(ModelAnswer).order_by(ModelAnswer.updated_at.desc(), ModelAnswer.id).limit(limit)
    if question_id is not None:
        stmt = stmt.where(ModelAnswer.question_id == question_id)
    if status is not None:
        stmt = stmt.where(ModelAnswer.status == status)
    return list((await session.execute(stmt)).scalars())


async def get_model_answer(session: AsyncSession, answer_id: uuid.UUID) -> ModelAnswer | None:
    return await session.get(ModelAnswer, answer_id)


async def answer_for_question(session: AsyncSession, question_id: uuid.UUID) -> ModelAnswer | None:
    result = await session.execute(
        select(ModelAnswer).where(ModelAnswer.question_id == question_id).limit(1)
    )
    return result.scalar_one_or_none()


async def points_with_keywords(
    session: AsyncSession, answer_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[AnswerPoint, list[str]]]]:
    """{model_answer_id: [(point, keywords A-Z)]} in point order."""
    by_answer: dict[uuid.UUID, list[tuple[AnswerPoint, list[str]]]] = {a: [] for a in answer_ids}
    if not answer_ids:
        return by_answer
    points = list(
        (
            await session.execute(
                select(AnswerPoint)
                .where(AnswerPoint.model_answer_id.in_(answer_ids))
                .order_by(AnswerPoint.model_answer_id, AnswerPoint.order_index, AnswerPoint.id)
            )
        ).scalars()
    )
    words: dict[uuid.UUID, list[str]] = {p.id: [] for p in points}
    if points:
        rows = await session.execute(
            select(Keyword.answer_point_id, Keyword.keyword)
            .where(Keyword.answer_point_id.in_(list(words)))
            .order_by(Keyword.answer_point_id, func.lower(Keyword.keyword))  # A-Z
        )
        for point_id, keyword in rows.all():
            words[point_id].append(keyword)
    for point in points:
        by_answer[point.model_answer_id].append((point, words[point.id]))
    return by_answer


async def add(session: AsyncSession, row: Any) -> None:
    session.add(row)
    await session.flush()


async def replace_keywords(session: AsyncSession, point_id: uuid.UUID, keywords: list[str]) -> None:
    await session.execute(delete(Keyword).where(Keyword.answer_point_id == point_id))
    session.add_all(Keyword(answer_point_id=point_id, keyword=k) for k in keywords)
    await session.flush()


async def approved_answer_for_question(
    session: AsyncSession, question_id: uuid.UUID
) -> ModelAnswer | None:
    """The approved model answer of a question (the newest one if there are several)."""
    result = await session.execute(
        select(ModelAnswer)
        .where(ModelAnswer.question_id == question_id, ModelAnswer.status == "approved")
        .order_by(ModelAnswer.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def answer_points(session: AsyncSession, answer_id: uuid.UUID) -> list[AnswerPoint]:
    result = await session.execute(
        select(AnswerPoint)
        .where(AnswerPoint.model_answer_id == answer_id)
        .order_by(AnswerPoint.order_index, AnswerPoint.id)
    )
    return list(result.scalars())


async def keyword_rows(
    session: AsyncSession, point_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Keyword]]:
    """{answer_point_id: keywords with their synonyms}."""
    rows: dict[uuid.UUID, list[Keyword]] = {p: [] for p in point_ids}
    if not point_ids:
        return rows
    result = await session.execute(
        select(Keyword)
        .where(Keyword.answer_point_id.in_(point_ids))
        .order_by(Keyword.answer_point_id, func.lower(Keyword.keyword))
    )
    for keyword in result.scalars():
        rows[keyword.answer_point_id].append(keyword)
    return rows


async def ai_answer_for_question(
    session: AsyncSession, question_id: uuid.UUID
) -> ModelAnswer | None:
    """The newest AI-made model answer of a question that isn't rejected / archived."""
    result = await session.execute(
        select(ModelAnswer)
        .where(
            ModelAnswer.question_id == question_id,
            ModelAnswer.source == "ai",
            ModelAnswer.status.in_(["draft", "pending_review", "approved"]),
        )
        .order_by(ModelAnswer.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def questions_with_approved_points(
    session: AsyncSession, question_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Questions that have an approved model answer with at least one marking point."""
    if not question_ids:
        return set()
    result = await session.execute(
        select(ModelAnswer.question_id)
        .join(AnswerPoint, AnswerPoint.model_answer_id == ModelAnswer.id)
        .where(ModelAnswer.question_id.in_(question_ids), ModelAnswer.status == "approved")
        .distinct()
    )
    return set(result.scalars())


async def approve_pending_ai_answers(
    session: AsyncSession, question_id: uuid.UUID, admin_id: uuid.UUID, now: datetime
) -> None:
    """Approve the AI-written model answer of this question, if one is waiting."""
    await session.execute(
        update(ModelAnswer)
        .where(
            ModelAnswer.question_id == question_id,
            ModelAnswer.source == "ai",
            ModelAnswer.status == ContentStatus.PENDING_REVIEW,
        )
        .values(status=ContentStatus.APPROVED, approved_by=admin_id, approved_at=now)
    )
