"""All SQL queries for the quizzes module. Owner: Udith.

Tables: papers, paper_questions, attempts, responses (+ reads questions / mcq_options / topics)
Only this module's `service.py` may import this file.

A diagnostic test is stored like any paper: a `papers` row with paper_type="diagnostic",
its questions in `paper_questions`, and one `attempts` row with one `responses` row per answer.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    Attempt,
    MCQOption,
    Paper,
    PaperQuestion,
    Question,
    Response,
    Topic,
)
from shared.enums import ContentStatus, QuestionType

DIAGNOSTIC = "diagnostic"  # papers.paper_type of diagnostic tests


async def count_papers(session: AsyncSession) -> int:
    """Example query showing the pattern."""
    result = await session.execute(select(func.count()).select_from(Attempt))
    return result.scalar_one()


@dataclass
class McqRow:
    """One MCQ with its options, ready to show (options sorted A, B, C...)."""

    id: uuid.UUID
    unit_id: uuid.UUID
    stem: str
    options: list[MCQOption] = field(default_factory=list)

    @property
    def correct_option_id(self) -> uuid.UUID | None:
        correct = [o.id for o in self.options if o.is_correct]
        return correct[0] if len(correct) == 1 else None


async def _attach_options(session: AsyncSession, rows: list[McqRow]) -> list[McqRow]:
    if not rows:
        return rows
    by_id = {r.id: r for r in rows}
    options = await session.execute(
        select(MCQOption)
        .where(MCQOption.question_id.in_(list(by_id)))
        .order_by(MCQOption.question_id, MCQOption.label)
    )
    for option in options.scalars():
        by_id[option.question_id].options.append(option)
    return rows


async def diagnostic_candidates(session: AsyncSession) -> list[McqRow]:
    """Every approved MCQ whose topic is in the current syllabus (not outdated)."""
    result = await session.execute(
        select(Question.id, Topic.unit_id, Question.stem)
        .join(Topic, Topic.id == Question.topic_id)
        .where(
            Question.status == ContentStatus.APPROVED,
            Question.question_type == QuestionType.MCQ,
            Topic.is_outdated.is_(False),
        )
    )
    rows = [McqRow(id=qid, unit_id=unit_id, stem=stem) for qid, unit_id, stem in result.all()]
    return await _attach_options(session, rows)


async def has_graded_diagnostic(session: AsyncSession, user_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(Attempt.id)
        .join(Paper, Paper.id == Attempt.paper_id)
        .where(
            Attempt.user_id == user_id,
            Paper.paper_type == DIAGNOSTIC,
            Attempt.status == "graded",
        )
        .limit(1)
    )
    return result.first() is not None


async def latest_diagnostic_attempt(
    session: AsyncSession, user_id: uuid.UUID, status: str
) -> Attempt | None:
    result = await session.execute(
        select(Attempt)
        .join(Paper, Paper.id == Attempt.paper_id)
        .where(
            Attempt.user_id == user_id,
            Paper.paper_type == DIAGNOSTIC,
            Attempt.status == status,
        )
        .order_by(Attempt.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_diagnostic_attempt(session: AsyncSession, attempt_id: uuid.UUID) -> Attempt | None:
    result = await session.execute(
        select(Attempt)
        .join(Paper, Paper.id == Attempt.paper_id)
        .where(Attempt.id == attempt_id, Paper.paper_type == DIAGNOSTIC)
    )
    return result.scalar_one_or_none()


async def create_diagnostic(
    session: AsyncSession,
    user_id: uuid.UUID,
    question_ids: list[uuid.UUID],
    minutes: int,
) -> Attempt:
    """Paper + paper_questions + an in-progress attempt. No commit."""
    paper = Paper(
        title="Diagnostic test",
        paper_type=DIAGNOSTIC,
        duration_minutes=minutes,
        total_marks=len(question_ids),
        status=ContentStatus.APPROVED,
        created_by=user_id,
    )
    session.add(paper)
    await session.flush()
    session.add_all(
        PaperQuestion(paper_id=paper.id, question_id=qid, position=i, marks=1)
        for i, qid in enumerate(question_ids, start=1)
    )
    attempt = Attempt(paper_id=paper.id, user_id=user_id, status="in_progress")
    session.add(attempt)
    await session.flush()
    return attempt


async def attempt_questions(session: AsyncSession, paper_id: uuid.UUID) -> list[McqRow]:
    """The paper's questions in order, with options and unit."""
    result = await session.execute(
        select(Question.id, Topic.unit_id, Question.stem)
        .join(PaperQuestion, PaperQuestion.question_id == Question.id)
        .join(Topic, Topic.id == Question.topic_id)
        .where(PaperQuestion.paper_id == paper_id)
        .order_by(PaperQuestion.position)
    )
    rows = [McqRow(id=qid, unit_id=unit_id, stem=stem) for qid, unit_id, stem in result.all()]
    return await _attach_options(session, rows)


async def get_responses(session: AsyncSession, attempt_id: uuid.UUID) -> dict[uuid.UUID, Response]:
    """{question_id: response} for an attempt."""
    result = await session.execute(select(Response).where(Response.attempt_id == attempt_id))
    return {r.question_id: r for r in result.scalars()}


async def add_response(session: AsyncSession, response: Response) -> None:
    session.add(response)
    await session.flush()
