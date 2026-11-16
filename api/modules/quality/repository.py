"""All SQL queries for the quality module. Owner: Udith.

Tables: question_reviews, question_reports, question_stats
Read-only for the admin review queue: questions, topics, units.
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Integer, func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    Question,
    QuestionReport,
    QuestionReview,
    QuestionStats,
    Topic,
    Unit,
)
from shared.enums import ContentStatus, ModerationStatus

# AI questions an admin has not decided on yet.
WAITING = (ContentStatus.DRAFT, ContentStatus.PENDING_REVIEW)


async def count_question_reviews(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(QuestionReview))
    return result.scalar_one()


async def review_queue(session: AsyncSession) -> list[tuple[Question, Topic | None, Unit | None]]:
    """AI-generated questions waiting for review, oldest first (the queue order)."""
    result = await session.execute(
        select(Question, Topic, Unit)
        .outerjoin(Topic, Topic.id == Question.topic_id)
        .outerjoin(Unit, Unit.id == Question.unit_id)
        .where(
            Question.source == "ai",
            Question.status.in_(WAITING),
            Question.is_outdated.is_(False),
        )
        .order_by(Question.created_at, Question.id)
    )
    return [(q, t, u) for q, t, u in result.all()]


async def latest_ai_checks(
    session: AsyncSession, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """{question_id: checks} of the newest AI review (the REVIEW_QUESTIONS output)."""
    if not question_ids:
        return {}
    result = await session.execute(
        select(QuestionReview.question_id, QuestionReview.checks)
        .where(
            QuestionReview.question_id.in_(question_ids),
            QuestionReview.reviewer_type == "ai",
        )
        .ext(distinct_on(QuestionReview.question_id))
        .order_by(QuestionReview.question_id, QuestionReview.created_at.desc())
    )
    return {qid: checks or {} for qid, checks in result.all()}


async def open_report_counts(
    session: AsyncSession, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[str, int]]]:
    """{question_id: [(reason, how many open reports)]}, most reported first."""
    by_question: dict[uuid.UUID, list[tuple[str, int]]] = {}
    if not question_ids:
        return by_question
    result = await session.execute(
        select(QuestionReport.question_id, QuestionReport.reason, func.count())
        .where(
            QuestionReport.question_id.in_(question_ids),
            QuestionReport.status == ModerationStatus.PENDING,
        )
        .group_by(QuestionReport.question_id, QuestionReport.reason)
        .order_by(func.count().desc(), QuestionReport.reason)
    )
    for qid, reason, n in result.all():
        by_question.setdefault(qid, []).append((reason, int(n)))
    return by_question


async def same_stem_numbers(
    session: AsyncSession, questions: list[Question]
) -> dict[uuid.UUID, int]:
    """{question_id: number of another question with exactly the same text (any case)}."""
    if not questions:
        return {}
    stems = {q.id: " ".join(q.stem.lower().split()) for q in questions}
    normalized = func.lower(func.regexp_replace(func.trim(Question.stem), r"\s+", " ", "g"))
    result = await session.execute(
        select(Question.id, Question.number, normalized.label("stem")).where(
            normalized.in_(set(stems.values())),
            Question.status != ContentStatus.ARCHIVED,
        )
    )
    rows = result.all()
    duplicates: dict[uuid.UUID, int] = {}
    for qid, stem in stems.items():
        other = next((n for i, n, s in rows if s == stem and i != qid), None)
        if other is not None:
            duplicates[qid] = other
    return duplicates


async def add_review(session: AsyncSession, review: QuestionReview) -> None:
    session.add(review)
    await session.flush()


async def average_review_minutes(session: AsyncSession, since: datetime) -> float | None:
    """Average minutes from question creation to the admin's decision, for decisions since."""
    minutes = func.extract("epoch", QuestionReview.created_at - Question.created_at) / 60
    result = await session.execute(
        select(func.avg(minutes))
        .join(Question, Question.id == QuestionReview.question_id)
        .where(QuestionReview.reviewer_type == "admin", QuestionReview.created_at >= since)
    )
    value = result.scalar_one()
    return float(value) if value is not None else None


async def pending_counts(session: AsyncSession, older_than: datetime) -> tuple[int, int]:
    """For the dashboard: (AI questions waiting for review, how many of them are older)."""
    result = await session.execute(
        select(func.count(), func.count().filter(Question.created_at < older_than)).where(
            Question.source == "ai",
            Question.status.in_(WAITING),
            Question.is_outdated.is_(False),
        )
    )
    total, old = result.one()
    return int(total), int(old)


async def ai_questions_per_day(session: AsyncSession, since: datetime) -> dict[date, int]:
    """{Sri Lanka date: AI questions created} - for the dashboard."""
    day = func.date(func.timezone("Asia/Colombo", Question.created_at))
    result = await session.execute(
        select(day, func.count())
        .where(Question.source == "ai", Question.created_at >= since)
        .group_by(day)
    )
    return {d: int(n) for d, n in result.all()}


# ---------------------------------------------------------------- student reports + stats
async def get_question(session: AsyncSession, question_id: uuid.UUID) -> Question | None:
    return await session.get(Question, question_id)


async def open_report_by(
    session: AsyncSession, question_id: uuid.UUID, user_id: uuid.UUID
) -> QuestionReport | None:
    result = await session.execute(
        select(QuestionReport)
        .where(
            QuestionReport.question_id == question_id,
            QuestionReport.user_id == user_id,
            QuestionReport.status == ModerationStatus.PENDING,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def add_report(session: AsyncSession, report: QuestionReport) -> None:
    session.add(report)
    await session.flush()


async def count_open_reporters(session: AsyncSession, question_id: uuid.UUID) -> int:
    """How many different students have an open report on this question."""
    result = await session.execute(
        select(func.count(func.distinct(QuestionReport.user_id))).where(
            QuestionReport.question_id == question_id,
            QuestionReport.status == ModerationStatus.PENDING,
        )
    )
    return int(result.scalar_one())


async def upsert_stats(
    session: AsyncSession, question_id: uuid.UUID, correct: bool, label: str | None
) -> QuestionStats:
    """Add one answer to the question's running statistics and return the row. No commit."""
    stmt = insert(QuestionStats).values(
        question_id=question_id,
        attempts_count=1,
        correct_count=int(correct),
        option_counts={label: 1} if label else {},
    )
    counts: Any = QuestionStats.option_counts
    if label:
        counts = func.jsonb_set(
            QuestionStats.option_counts,
            [label],
            func.to_jsonb(
                func.coalesce(QuestionStats.option_counts[label].astext.cast(Integer), 0) + 1
            ),
        )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[QuestionStats.question_id],
            set_={
                "attempts_count": QuestionStats.attempts_count + 1,
                "correct_count": QuestionStats.correct_count + int(correct),
                "option_counts": counts,
                "updated_at": func.now(),
            },
        )
    )
    result = await session.execute(
        select(QuestionStats)
        .where(QuestionStats.question_id == question_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()
