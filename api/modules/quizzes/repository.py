"""All SQL queries for the quizzes module. Owner: Udith.

Tables: papers, paper_questions, attempts, responses (+ reads questions / mcq_options / topics)
Only this module's `service.py` may import this file.

A diagnostic test is stored like any paper: a `papers` row with paper_type="diagnostic",
its questions in `paper_questions`, and one `attempts` row with one `responses` row per answer.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    Attempt,
    MCQOption,
    Misconception,
    Paper,
    PaperQuestion,
    Question,
    QuestionConcept,
    Response,
    Topic,
)
from shared.enums import AttemptKind, AttemptMode, ContentStatus, QuestionType

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
    attempt = Attempt(
        paper_id=paper.id,
        user_id=user_id,
        kind=AttemptKind.DIAGNOSTIC,  # the database allows one unfinished diagnostic per student
        status="in_progress",
        question_ids=list(question_ids),
    )
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


# =========================================================================== quizzes (practice)
# A quiz is stored like the diagnostic: a `papers` row (paper_type="quiz"), its questions in
# `paper_questions`, one `attempts` row (kind="quiz") and one `responses` row per answer.

QUIZ = "quiz"


@dataclass
class QuizRow:
    """One MCQ of a quiz with everything the question and feedback screens show."""

    id: uuid.UUID
    unit_id: uuid.UUID
    topic_id: uuid.UUID
    topic_title: str
    stem: str
    difficulty: str
    explanation: str | None
    options: list[MCQOption] = field(default_factory=list)

    @property
    def correct_option(self) -> MCQOption | None:
        correct = [o for o in self.options if o.is_correct]
        return correct[0] if len(correct) == 1 else None


def _quiz_select() -> Any:
    return select(
        Question.id,
        Topic.unit_id,
        Question.topic_id,
        Topic.title.label("topic_title"),
        Question.stem,
        Question.difficulty,
        Question.explanation,
    ).join(Topic, Topic.id == Question.topic_id)


async def _quiz_rows(session: AsyncSession, stmt: Any) -> list[QuizRow]:
    rows = [
        QuizRow(
            id=r.id,
            unit_id=r.unit_id,
            topic_id=r.topic_id,
            topic_title=r.topic_title,
            stem=r.stem,
            difficulty=str(getattr(r.difficulty, "value", r.difficulty)),
            explanation=r.explanation,
        )
        for r in (await session.execute(stmt)).all()
    ]
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


async def quiz_candidates(
    session: AsyncSession,
    *,
    unit_id: uuid.UUID | None = None,
    topic_id: uuid.UUID | None = None,
    concept_id: uuid.UUID | None = None,
    question_ids: list[uuid.UUID] | None = None,
    difficulty: str | None = None,
) -> list[QuizRow]:
    """Approved MCQs of the current syllabus that match the filters."""
    stmt = _quiz_select().where(
        Question.status == ContentStatus.APPROVED,
        Question.question_type == QuestionType.MCQ,
        Question.is_outdated.is_(False),
        Topic.is_outdated.is_(False),
    )
    if unit_id is not None:
        stmt = stmt.where(Topic.unit_id == unit_id)
    if topic_id is not None:
        stmt = stmt.where(Question.topic_id == topic_id)
    if difficulty is not None:
        stmt = stmt.where(Question.difficulty == difficulty)
    if question_ids is not None:
        stmt = stmt.where(Question.id.in_(question_ids))
    if concept_id is not None:
        stmt = stmt.where(
            Question.id.in_(
                select(QuestionConcept.question_id).where(QuestionConcept.concept_id == concept_id)
            )
        )
    return await _quiz_rows(session, stmt)


async def quiz_questions(session: AsyncSession, question_ids: list[uuid.UUID]) -> list[QuizRow]:
    """These questions in the given (frozen) order."""
    if not question_ids:
        return []
    rows = {
        r.id: r
        for r in await _quiz_rows(session, _quiz_select().where(Question.id.in_(question_ids)))
    }
    return [rows[q] for q in question_ids if q in rows]


async def seen_question_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Questions this student has already answered in any attempt."""
    result = await session.execute(
        select(Response.question_id)
        .join(Attempt, Attempt.id == Response.attempt_id)
        .where(Attempt.user_id == user_id, Response.selected_option_id.is_not(None))
        .distinct()
    )
    return set(result.scalars())


async def concept_links(
    session: AsyncSession, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    if not question_ids:
        return {}
    result = await session.execute(
        select(QuestionConcept.question_id, QuestionConcept.concept_id).where(
            QuestionConcept.question_id.in_(question_ids)
        )
    )
    links: dict[uuid.UUID, list[uuid.UUID]] = {}
    for question_id, concept_id in result.all():
        links.setdefault(question_id, []).append(concept_id)
    return links


async def create_quiz(
    session: AsyncSession,
    user_id: uuid.UUID,
    question_ids: list[uuid.UUID],
    *,
    title: str,
    unit_id: uuid.UUID | None,
    topic_id: uuid.UUID | None,
    minutes: int | None,
    blueprint: dict[str, Any],
) -> Attempt:
    """Paper + paper_questions + an in-progress attempt. No commit."""
    paper = Paper(
        title=title[:200],
        paper_type=QUIZ,
        unit_id=unit_id,
        blueprint=blueprint,
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
    attempt = Attempt(
        paper_id=paper.id,
        user_id=user_id,
        kind=AttemptKind.QUIZ,
        mode=AttemptMode.TIMED if minutes else AttemptMode.PRACTICE,
        status="in_progress",
        unit_id=unit_id,
        topic_id=topic_id,
        question_ids=list(question_ids),
        time_limit_minutes=minutes,
    )
    session.add(attempt)
    await session.flush()
    return attempt


async def get_quiz_attempt(session: AsyncSession, attempt_id: uuid.UUID) -> Attempt | None:
    result = await session.execute(
        select(Attempt).where(Attempt.id == attempt_id, Attempt.kind == AttemptKind.QUIZ)
    )
    return result.scalar_one_or_none()


async def get_paper(session: AsyncSession, paper_id: uuid.UUID) -> Paper | None:
    return await session.get(Paper, paper_id)


async def get_misconceptions(
    session: AsyncSession, misconception_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Misconception]:
    if not misconception_ids:
        return {}
    result = await session.execute(
        select(Misconception).where(Misconception.id.in_(misconception_ids))
    )
    return {m.id: m for m in result.scalars()}


async def recent_quizzes(
    session: AsyncSession, user_id: uuid.UUID, limit: int
) -> list[tuple[Attempt, str]]:
    """The student's newest quizzes with the paper title."""
    result = await session.execute(
        select(Attempt, Paper.title)
        .join(Paper, Paper.id == Attempt.paper_id)
        .where(Attempt.user_id == user_id, Attempt.kind == AttemptKind.QUIZ)
        .order_by(Attempt.created_at.desc())
        .limit(limit)
    )
    return [(attempt, title) for attempt, title in result.all()]
