"""All SQL queries for the questions module. Owner: Udith.

Tables: questions, mcq_options, misconceptions, question_concepts
Only this module's `service.py` may import this file.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import MCQOption, Question
from shared.enums import ContentStatus, QuestionType


async def count_questions(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Question))
    return result.scalar_one()


async def random_approved_mcqs(
    session: AsyncSession, topic_id: uuid.UUID, limit: int
) -> list[tuple[Question, list[MCQOption]]]:
    """Up to `limit` approved MCQs of a topic in random order, each with its options (A, B, ...)."""
    questions = (
        (
            await session.execute(
                select(Question)
                .where(
                    Question.topic_id == topic_id,
                    Question.question_type == QuestionType.MCQ,
                    Question.status == ContentStatus.APPROVED,
                )
                .order_by(func.random())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not questions:
        return []
    options = (
        (
            await session.execute(
                select(MCQOption)
                .where(MCQOption.question_id.in_([q.id for q in questions]))
                .order_by(MCQOption.label)
            )
        )
        .scalars()
        .all()
    )
    by_question: dict[uuid.UUID, list[MCQOption]] = {q.id: [] for q in questions}
    for option in options:
        by_question[option.question_id].append(option)
    return [(q, by_question[q.id]) for q in questions]


async def get_by_id(
    session: AsyncSession, question_id: uuid.UUID
) -> tuple[Question, list[MCQOption]] | None:
    """Fetch one question with its MCQ options."""
    question = await session.get(Question, question_id)
    if not question:
        return None
    options = (
        (
            await session.execute(
                select(MCQOption)
                .where(MCQOption.question_id == question_id)
                .order_by(MCQOption.label)
            )
        )
        .scalars()
        .all()
    )
    return question, list(options)


async def list_by_topic(
    session: AsyncSession, topic_id: uuid.UUID, limit: int = 10
) -> list[tuple[Question, list[MCQOption]]]:
    """Approved questions for a topic, with their options in order."""
    questions = (
        (
            await session.execute(
                select(Question)
                .where(
                    Question.topic_id == topic_id,
                    Question.status == ContentStatus.APPROVED,
                )
                .order_by(Question.created_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not questions:
        return []
    options = (
        (
            await session.execute(
                select(MCQOption)
                .where(MCQOption.question_id.in_([q.id for q in questions]))
                .order_by(MCQOption.label)
            )
        )
        .scalars()
        .all()
    )
    by_question: dict[uuid.UUID, list[MCQOption]] = {q.id: [] for q in questions}
    for opt in options:
        by_question[opt.question_id].append(opt)
    return [(q, by_question[q.id]) for q in questions]

