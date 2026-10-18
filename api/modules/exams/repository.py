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


async def get_grading_rows(session: AsyncSession, paper_id: uuid.UUID) -> list[GradingRow]:
    """The paper's MCQs in order, with options and topic title."""
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
) -> Attempt:
    """Store a graded attempt and one `responses` row per question. No commit."""
    now = datetime.now(UTC)
    attempt = Attempt(
        paper_id=paper_id,
        user_id=user_id,
        status="graded",
        started_at=now,
        submitted_at=now,
        score=score,
    )
    session.add(attempt)
    await session.flush()
    session.add_all(Response(attempt_id=attempt.id, **r) for r in responses)
    await session.flush()
    return attempt
