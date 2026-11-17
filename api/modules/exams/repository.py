"""All SQL queries for the exams module. Owner: Udith.

Tables: papers, paper_questions, attempts, responses (+ questions / mcq_options rows that
belong to an AI-generated paper).
Only this module's `service.py` may import this file.

Replaces Udith's original `paper_store.py` (which kept papers as one JSON column): every
generated question is now a real `questions` row with `mcq_options`, so it can be reviewed,
reused and analysed like any other question.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    Attempt,
    MCQOption,
    Paper,
    PaperQuestion,
    Question,
    Response,
    Topic,
    Unit,
)
from shared.enums import AttemptKind, ContentStatus, Difficulty, PaperKind, QuestionType

LETTERS = "ABCDE"


async def count_papers(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Paper))
    return result.scalar_one()


@dataclass
class SavedQuestion:
    id: uuid.UUID
    topic_id: uuid.UUID | None
    question: str
    options: list[str]
    correct_answer: str
    marks: int


async def save_generated_paper(
    session: AsyncSession,
    *,
    title: str,
    user_id: uuid.UUID,
    questions: list[dict[str, Any]],
    prompt_version: str | None,
) -> tuple[Paper, list[SavedQuestion]]:
    """Insert the paper, its AI questions (status pending_review) and their options. No commit."""
    paper = Paper(
        title=title,
        paper_type="ai_generated",  # a personal practice paper for `created_by`
        total_marks=sum(int(q.get("marks", 1)) for q in questions),
        created_by=user_id,
    )
    session.add(paper)
    await session.flush()

    saved: list[SavedQuestion] = []
    for position, item in enumerate(questions, start=1):
        question = Question(
            topic_id=uuid.UUID(item["topic_id"]) if item.get("topic_id") else None,
            # Unit papers (generate-by-units) have a unit but no topic
            unit_id=uuid.UUID(item["unit_id"]) if item.get("unit_id") else None,
            question_type=QuestionType.MCQ,
            stem=item["question"],
            explanation=item.get("explanation") or None,
            marks=int(item.get("marks", 1)),
            source="ai",
            status=ContentStatus.PENDING_REVIEW,  # admins review AI questions later
            prompt_version=prompt_version,
            created_by=user_id,
        )
        session.add(question)
        await session.flush()
        for label, text in zip(LETTERS, item["options"], strict=False):
            session.add(
                MCQOption(
                    question_id=question.id,
                    label=label,
                    text=text,
                    is_correct=text == item["correct_answer"],
                )
            )
        session.add(
            PaperQuestion(
                paper_id=paper.id, question_id=question.id, position=position, marks=question.marks
            )
        )
        saved.append(
            SavedQuestion(
                id=question.id,
                topic_id=question.topic_id,
                question=question.stem,
                options=list(item["options"]),
                correct_answer=item["correct_answer"],
                marks=question.marks,
            )
        )
    await session.flush()
    return paper, saved


async def get_paper(session: AsyncSession, paper_id: uuid.UUID) -> Paper | None:
    return await session.get(Paper, paper_id)


@dataclass
class GradingRow:
    """Everything needed to mark one question of a paper."""

    question_id: uuid.UUID
    topic: str
    question: str
    marks: int
    option_ids: list[uuid.UUID]  # in letter order A, B, C...
    options: list[str]
    correct_answer: str
    question_type: QuestionType = QuestionType.MCQ


async def get_grading_rows(session: AsyncSession, paper_id: uuid.UUID) -> list[GradingRow]:
    """The paper's questions in order: MCQs with their options, written ones without."""
    rows = (
        await session.execute(
            select(PaperQuestion, Question, Topic.title)
            .join(Question, Question.id == PaperQuestion.question_id)
            .outerjoin(Topic, Topic.id == Question.topic_id)
            .where(PaperQuestion.paper_id == paper_id)
            .order_by(PaperQuestion.position)
        )
    ).all()
    if not rows:
        return []
    question_ids = [q.id for _, q, _ in rows]
    options = (
        (
            await session.execute(
                select(MCQOption)
                .where(MCQOption.question_id.in_(question_ids))
                .order_by(MCQOption.question_id, MCQOption.label)
            )
        )
        .scalars()
        .all()
    )
    by_question: dict[uuid.UUID, list[MCQOption]] = {qid: [] for qid in question_ids}
    for option in options:
        by_question[option.question_id].append(option)

    result = []
    for paper_question, question, topic_title in rows:
        opts = by_question[question.id]
        result.append(
            GradingRow(
                question_id=question.id,
                topic=topic_title or "General",
                question=question.stem,
                marks=paper_question.marks,
                option_ids=[o.id for o in opts],
                options=[o.text for o in opts],
                correct_answer=next((o.text for o in opts if o.is_correct), ""),
                question_type=question.question_type,
            )
        )
    return result


async def save_attempt(
    session: AsyncSession,
    *,
    paper_id: uuid.UUID,
    user_id: uuid.UUID,
    score: float,
    responses: list[dict[str, Any]],
    status: str = "graded",
) -> Attempt:
    """Store a marked attempt and one `responses` row per question. No commit.

    status: "graded" (everything marked) or "submitted" (written answers still being marked).
    A response dict may carry its own "id" (to link an evaluation to it)."""
    now = datetime.now(UTC)
    attempt = Attempt(
        paper_id=paper_id,
        user_id=user_id,
        kind=AttemptKind.EXAM,
        status=status,
        started_at=now,
        submitted_at=now,
        score=score,
    )
    session.add(attempt)
    await session.flush()
    session.add_all(Response(attempt_id=attempt.id, **r) for r in responses)
    await session.flush()
    return attempt


# --------------------------------------------------------------------------- written answers
async def get_attempt(session: AsyncSession, attempt_id: uuid.UUID) -> Attempt | None:
    return await session.get(Attempt, attempt_id)


async def get_response(session: AsyncSession, response_id: uuid.UUID) -> Response | None:
    return await session.get(Response, response_id)


async def attempt_responses(session: AsyncSession, attempt_id: uuid.UUID) -> list[Response]:
    result = await session.execute(select(Response).where(Response.attempt_id == attempt_id))
    return list(result.scalars())


# --------------------------------------------------------------------------- list / view papers
def _scope_unit_join() -> ColumnElement[bool]:
    """Join condition: a question's unit, or its topic's unit."""
    return Unit.id == func.coalesce(Question.unit_id, Topic.unit_id)


def outdated_expr() -> ColumnElement[bool]:
    """True when the question, its topic or its unit is marked outdated."""
    return or_(
        Question.is_outdated.is_(True),
        func.coalesce(Topic.is_outdated, false()),
        func.coalesce(Unit.is_outdated, false()),
    )


@dataclass
class PaperRow:
    paper: Paper
    question_count: int
    outdated_count: int
    question_types: list[str]


async def list_past_papers(
    session: AsyncSession,
    *,
    year: int | None,
    question_type: QuestionType | None,
    offset: int,
    limit: int,
) -> tuple[list[PaperRow], int]:
    """Approved past papers, newest year first, with question counts."""
    stats = (
        select(
            PaperQuestion.paper_id.label("paper_id"),
            func.count().label("n"),
            func.count().filter(outdated_expr()).label("outdated"),
            func.array_agg(func.distinct(Question.question_type)).label("types"),
        )
        .join(Question, Question.id == PaperQuestion.question_id)
        .outerjoin(Topic, Topic.id == Question.topic_id)
        .outerjoin(Unit, _scope_unit_join())
        .group_by(PaperQuestion.paper_id)
        .subquery()
    )
    filters: list[Any] = [
        Paper.paper_type == PaperKind.PAST_PAPER.value,
        Paper.status == ContentStatus.APPROVED,
    ]
    if year is not None:
        filters.append(Paper.year == year)
    if question_type is not None:
        filters.append(stats.c.types.any(question_type.value))
    joined = select(Paper).join(stats, stats.c.paper_id == Paper.id).where(*filters)
    total = await session.scalar(select(func.count()).select_from(joined.subquery()))
    rows = await session.execute(
        select(Paper, stats.c.n, stats.c.outdated, stats.c.types)
        .join(stats, stats.c.paper_id == Paper.id)
        .where(*filters)
        .order_by(Paper.year.desc().nulls_last(), Paper.title, Paper.id)
        .offset(offset)
        .limit(limit)
    )
    out = [
        PaperRow(
            paper, int(n), int(outdated), sorted(str(getattr(t, "value", t)) for t in types or [])
        )
        for paper, n, outdated, types in rows.all()
    ]
    return out, int(total or 0)


@dataclass
class PaperQuestionRow:
    position: int
    marks: int
    question: Question
    topic_title: str | None
    is_outdated: bool
    options: list[MCQOption]


async def paper_questions(session: AsyncSession, paper_id: uuid.UUID) -> list[PaperQuestionRow]:
    """Every question of a paper in order, with its topic, outdated flag and options."""
    rows = (
        await session.execute(
            select(PaperQuestion, Question, Topic.title, outdated_expr())
            .join(Question, Question.id == PaperQuestion.question_id)
            .outerjoin(Topic, Topic.id == Question.topic_id)
            .outerjoin(Unit, _scope_unit_join())
            .where(PaperQuestion.paper_id == paper_id)
            .order_by(PaperQuestion.position)
        )
    ).all()
    ids = [q.id for _, q, _, _ in rows]
    options: dict[uuid.UUID, list[MCQOption]] = {i: [] for i in ids}
    if ids:
        result = await session.execute(
            select(MCQOption)
            .where(MCQOption.question_id.in_(ids))
            .order_by(MCQOption.question_id, MCQOption.label)
        )
        for option in result.scalars():
            options[option.question_id].append(option)
    return [
        PaperQuestionRow(pq.position, pq.marks, q, title, bool(outdated), options[q.id])
        for pq, q, title, outdated in rows
    ]


# --------------------------------------------------------------------------- blueprint papers
TYPE_ORDER = {QuestionType.MCQ: 0, QuestionType.STRUCTURED: 1, QuestionType.ESSAY: 2}


async def questions_by_id(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, Question]:
    if not ids:
        return {}
    result = await session.execute(select(Question).where(Question.id.in_(ids)))
    return {q.id: q for q in result.scalars()}


async def add_generated_question(
    session: AsyncSession,
    item: dict[str, Any],
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID | None,
) -> Question:
    """One AI question of a model paper (status pending_review), with its options. No commit."""
    kind = QuestionType(str(item.get("question_type") or "mcq"))
    try:
        difficulty = Difficulty(str(item.get("difficulty") or "medium"))
    except ValueError:
        difficulty = Difficulty.MEDIUM
    question = Question(
        topic_id=uuid.UUID(item["topic_id"]) if item.get("topic_id") else None,
        unit_id=uuid.UUID(item["unit_id"]) if item.get("unit_id") else None,
        question_type=kind,
        difficulty=difficulty,
        stem=str(item["question"]),
        explanation=item.get("explanation") or None,
        marks=max(1, int(item.get("marks") or 1)),
        source="ai",
        status=ContentStatus.PENDING_REVIEW,  # admins review AI questions later
        prompt_version=item.get("prompt_version"),
        job_id=job_id,
        created_by=user_id,
    )
    session.add(question)
    await session.flush()
    if kind == QuestionType.MCQ:
        for label, text in zip(LETTERS, item["options"], strict=False):
            session.add(
                MCQOption(
                    question_id=question.id,
                    label=label,
                    text=text,
                    is_correct=text == item["correct_answer"],
                )
            )
    return question


async def save_blueprint_paper(
    session: AsyncSession,
    *,
    title: str,
    user_id: uuid.UUID,
    questions: list[Question],
    blueprint: dict[str, Any],
    unit_ids: list[uuid.UUID],
    duration_minutes: int | None,
    job_id: uuid.UUID | None,
) -> Paper:
    """The student's model paper: MCQs first, then structured, then essay. No commit."""
    ordered = sorted(questions, key=lambda q: TYPE_ORDER.get(q.question_type, 9))
    paper = Paper(
        title=title,
        paper_type=PaperKind.AI_GENERATED.value,  # a personal practice paper for `created_by`
        unit_ids=unit_ids,
        blueprint=blueprint,
        duration_minutes=duration_minutes,
        total_marks=sum(q.marks for q in ordered),
        created_by=user_id,
        job_id=job_id,
    )
    session.add(paper)
    await session.flush()
    session.add_all(
        PaperQuestion(paper_id=paper.id, question_id=q.id, position=n, marks=q.marks)
        for n, q in enumerate(ordered, start=1)
    )
    await session.flush()
    return paper
