"""All SQL queries for the questions module. Owner: Udith.

Tables: questions, mcq_options, misconceptions, question_concepts
Read-only for the admin question bank: topics, units, responses, paper_questions.
Admin past papers: past_papers, past_paper_questions.
Only this module's `service.py` may import this file.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    MCQOption,
    Misconception,
    PaperQuestion,
    PastPaper,
    PastPaperQuestion,
    Question,
    QuestionConcept,
    Response,
    Topic,
    Unit,
)
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
                    Question.is_outdated.is_(False),
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
                    Question.is_outdated.is_(False),
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


# ---------------------------------------------------------------- admin: question bank
@dataclass
class BankRow:
    question: Question
    unit_number: int | None
    topic_title: str | None


def _bank_filters(
    unit_number: int | None,
    question_type: QuestionType | None,
    difficulty: str | None,
    status: str | None,
) -> list[Any]:
    filters: list[Any] = []
    if unit_number is not None:
        filters.append(Unit.number == unit_number)
    if question_type is not None:
        filters.append(Question.question_type == question_type)
    if difficulty is not None:
        filters.append(Question.difficulty == difficulty)
    if status == "outdated":
        filters.append(Question.is_outdated.is_(True))
    elif status is not None:
        filters.append(Question.status == status)
    else:  # deleted-but-used questions are archived; they leave the bank
        filters.append(Question.status != ContentStatus.ARCHIVED)
    return filters


async def list_bank(
    session: AsyncSession,
    *,
    unit_number: int | None,
    question_type: QuestionType | None,
    difficulty: str | None,
    status: str | None,
    offset: int,
    limit: int,
) -> tuple[list[BankRow], int, int]:
    """(one page, newest first; total matching; how many of those are past-paper questions)."""
    filters = _bank_filters(unit_number, question_type, difficulty, status)
    base = (
        select(Question, Unit.number, Topic.title)
        .outerjoin(Unit, Unit.id == Question.unit_id)
        .outerjoin(Topic, Topic.id == Question.topic_id)
        .where(*filters)
    )
    counts = await session.execute(
        select(
            func.count(),
            func.count().filter(Question.source == "past_paper"),
        )
        .select_from(Question)
        .outerjoin(Unit, Unit.id == Question.unit_id)
        .where(*filters)
    )
    total, past_paper = counts.one()
    rows = await session.execute(base.order_by(Question.number.desc()).offset(offset).limit(limit))
    return [BankRow(q, n, t) for q, n, t in rows.all()], int(total), int(past_paper)


async def get_question(session: AsyncSession, question_id: uuid.UUID) -> Question | None:
    return await session.get(Question, question_id)


async def get_questions(session: AsyncSession, ids: list[uuid.UUID]) -> list[Question]:
    result = await session.execute(select(Question).where(Question.id.in_(ids)))
    return list(result.scalars())


async def options_with_misconceptions(
    session: AsyncSession, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[MCQOption, str | None]]]:
    """{question_id: [(option, misconception title)]} in label order."""
    by_question: dict[uuid.UUID, list[tuple[MCQOption, str | None]]] = {q: [] for q in question_ids}
    if not question_ids:
        return by_question
    result = await session.execute(
        select(MCQOption, Misconception.title)
        .outerjoin(Misconception, Misconception.id == MCQOption.misconception_id)
        .where(MCQOption.question_id.in_(question_ids))
        .order_by(MCQOption.question_id, MCQOption.label)
    )
    for option, title in result.all():
        by_question[option.question_id].append((option, title))
    return by_question


async def main_concept(session: AsyncSession, question_id: uuid.UUID) -> uuid.UUID | None:
    result = await session.execute(
        select(QuestionConcept.concept_id)
        .where(QuestionConcept.question_id == question_id)
        .order_by(QuestionConcept.weight.desc(), QuestionConcept.concept_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def set_concept(
    session: AsyncSession, question_id: uuid.UUID, concept_id: uuid.UUID | None
) -> None:
    """The question tests exactly this concept (or none)."""
    await session.execute(delete(QuestionConcept).where(QuestionConcept.question_id == question_id))
    if concept_id is not None:
        session.add(QuestionConcept(question_id=question_id, concept_id=concept_id))
    await session.flush()


async def find_misconception(
    session: AsyncSession, concept_id: uuid.UUID | None, title: str
) -> Misconception | None:
    stmt = select(Misconception).where(func.lower(Misconception.title) == title.lower())
    stmt = stmt.where(
        Misconception.concept_id == concept_id
        if concept_id is not None
        else Misconception.concept_id.is_(None)
    )
    return (await session.execute(stmt.limit(1))).scalar_one_or_none()


async def add(session: AsyncSession, row: Any) -> None:
    session.add(row)
    await session.flush()


async def delete_row(session: AsyncSession, row: Any) -> None:
    await session.delete(row)
    await session.flush()


async def used_question_ids(session: AsyncSession, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Questions that students answered or that are in a paper (never hard-deleted)."""
    answered = exists().where(Response.question_id == Question.id)
    in_paper = exists().where(PaperQuestion.question_id == Question.id)
    result = await session.execute(
        select(Question.id).where(Question.id.in_(ids), or_(answered, in_paper))
    )
    return set(result.scalars())


# ---------------------------------------------------------------- admin: past papers
async def list_past_papers(
    session: AsyncSession, low_confidence_below: float
) -> list[tuple[PastPaper, int, int]]:
    """(paper, questions extracted, how many of them have a low OCR confidence), newest first."""
    counts = (
        select(
            PastPaperQuestion.past_paper_id,
            func.count().label("n"),
            func.count()
            .filter(PastPaperQuestion.ocr_confidence < low_confidence_below)
            .label("low"),
        )
        .group_by(PastPaperQuestion.past_paper_id)
        .subquery()
    )
    result = await session.execute(
        select(PastPaper, func.coalesce(counts.c.n, 0), func.coalesce(counts.c.low, 0))
        .outerjoin(counts, counts.c.past_paper_id == PastPaper.id)
        .order_by(PastPaper.year.desc(), PastPaper.paper_type)
    )
    return [(p, int(n), int(low)) for p, n, low in result.all()]


async def past_paper_counts(
    session: AsyncSession, paper_id: uuid.UUID, low_confidence_below: float
) -> tuple[int, int]:
    result = await session.execute(
        select(
            func.count(),
            func.count().filter(PastPaperQuestion.ocr_confidence < low_confidence_below),
        ).where(PastPaperQuestion.past_paper_id == paper_id)
    )
    n, low = result.one()
    return int(n), int(low)


async def past_paper_exists(session: AsyncSession, year: int, paper_type: str) -> bool:
    result = await session.execute(
        select(PastPaper.id).where(PastPaper.year == year, PastPaper.paper_type == paper_type)
    )
    return result.first() is not None


async def get_past_paper(session: AsyncSession, paper_id: uuid.UUID) -> PastPaper | None:
    return await session.get(PastPaper, paper_id)


async def list_past_paper_questions(
    session: AsyncSession, paper_id: uuid.UUID
) -> list[PastPaperQuestion]:
    result = await session.execute(
        select(PastPaperQuestion)
        .where(PastPaperQuestion.past_paper_id == paper_id)
        .order_by(PastPaperQuestion.position)
    )
    return list(result.scalars())


async def get_past_paper_question(
    session: AsyncSession, question_id: uuid.UUID
) -> PastPaperQuestion | None:
    return await session.get(PastPaperQuestion, question_id)


async def replace_past_paper_questions(
    session: AsyncSession, paper_id: uuid.UUID, rows: list[PastPaperQuestion]
) -> None:
    """The newest extraction replaces any earlier one."""
    await session.execute(
        delete(PastPaperQuestion).where(PastPaperQuestion.past_paper_id == paper_id)
    )
    session.add_all(rows)
    await session.flush()


async def get_option(session: AsyncSession, option_id: uuid.UUID) -> MCQOption | None:
    return await session.get(MCQOption, option_id)


async def misconception_title(
    session: AsyncSession, misconception_id: uuid.UUID | None
) -> str | None:
    if misconception_id is None:
        return None
    row = await session.get(Misconception, misconception_id)
    return row.title if row else None
