"""All SQL queries for the knowledge_base module. Owner: Keshomigha.

Tables: model_answers, answer_points, keywords
Only this module's `service.py` may import this file.
"""

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AnswerPoint, Keyword, ModelAnswer


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
