"""All SQL queries for the visuals module. Owner: Mogith.

Tables: visuals, visual_reports
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AIJob, Topic, Unit, User, Visual, VisualReport
from shared.enums import ContentStatus, ModerationStatus

# A student's own visual is hidden once it is rejected (e.g. not Biology) or archived (failed).
HIDDEN_OWN_STATUSES = (ContentStatus.REJECTED, ContentStatus.ARCHIVED)


def visible_to(user_id: uuid.UUID) -> ColumnElement[bool]:
    """Approved visuals (everyone) + this student's own visuals that are not hidden."""
    return or_(
        Visual.status == ContentStatus.APPROVED,
        and_(Visual.created_by == user_id, Visual.status.not_in(HIDDEN_OWN_STATUSES)),
    )


async def get_visual(session: AsyncSession, visual_id: uuid.UUID) -> Visual | None:
    return await session.get(Visual, visual_id)


async def list_topic_visuals(
    session: AsyncSession, topic_id: uuid.UUID, user_id: uuid.UUID
) -> list[Visual]:
    """Visuals of a topic this student may see, newest first.

    Own visuals still being made (no Mermaid code and no image yet) are left out.
    """
    has_content = or_(Visual.mermaid_code.is_not(None), Visual.image_path.is_not(None))
    result = await session.execute(
        select(Visual)
        .where(Visual.topic_id == topic_id, visible_to(user_id), has_content)
        .order_by(Visual.created_at.desc(), Visual.id)
    )
    return list(result.scalars())


async def recent_requests(
    session: AsyncSession, user_id: uuid.UUID, since: datetime
) -> tuple[int, datetime | None]:
    """(how many visuals this student asked for since `since`, the oldest of them)."""
    result = await session.execute(
        select(func.count(), func.min(Visual.created_at)).where(
            Visual.created_by == user_id,
            Visual.is_ai_generated.is_(True),
            Visual.created_at >= since,
        )
    )
    count, oldest = result.one()
    return int(count), oldest


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> AIJob | None:
    return await session.get(AIJob, job_id)


async def get_pending_report(
    session: AsyncSession, visual_id: uuid.UUID, user_id: uuid.UUID
) -> VisualReport | None:
    result = await session.execute(
        select(VisualReport).where(
            VisualReport.visual_id == visual_id,
            VisualReport.user_id == user_id,
            VisualReport.status == ModerationStatus.PENDING,
        )
    )
    return result.scalar_one_or_none()


async def open_report_groups(
    session: AsyncSession,
) -> list[tuple[VisualReport, Visual, int, str | None]]:
    """Pending reports grouped per visual: (oldest report, visual, how many, creator's name)."""
    counts = (
        select(
            VisualReport.visual_id,
            func.count().label("n"),
            func.min(VisualReport.created_at).label("first_at"),
        )
        .where(VisualReport.status == ModerationStatus.PENDING)
        .group_by(VisualReport.visual_id)
        .subquery()
    )
    result = await session.execute(
        select(VisualReport, Visual, counts.c.n, User.display_name)
        .join(counts, counts.c.visual_id == VisualReport.visual_id)
        .join(Visual, Visual.id == VisualReport.visual_id)
        .outerjoin(User, User.id == Visual.created_by)
        .where(
            VisualReport.status == ModerationStatus.PENDING,
            VisualReport.created_at == counts.c.first_at,
        )
        .order_by(VisualReport.created_at, VisualReport.id)
    )
    seen: set[uuid.UUID] = set()
    rows = []
    for report, visual, n, name in result.all():
        if visual.id not in seen:  # two reports at the very same moment: keep one
            seen.add(visual.id)
            rows.append((report, visual, int(n), name))
    return rows


async def get_report(session: AsyncSession, report_id: uuid.UUID) -> VisualReport | None:
    return await session.get(VisualReport, report_id)


async def pending_reports_of(session: AsyncSession, visual_id: uuid.UUID) -> list[VisualReport]:
    result = await session.execute(
        select(VisualReport).where(
            VisualReport.visual_id == visual_id, VisualReport.status == ModerationStatus.PENDING
        )
    )
    return list(result.scalars())


# Visuals an admin still has to look at (student visuals stay draft until approved).
WAITING_FOR_REVIEW = (ContentStatus.DRAFT, ContentStatus.PENDING_REVIEW)


async def list_for_review(
    session: AsyncSession, status: ContentStatus | None, unit_number: int | None, limit: int
) -> list[tuple[Visual, Topic | None, Unit | None]]:
    """Finished visuals with their topic + unit. No status = the ones waiting for review."""
    has_content = or_(Visual.mermaid_code.is_not(None), Visual.image_path.is_not(None))
    stmt = (
        select(Visual, Topic, Unit)
        .outerjoin(Topic, Topic.id == Visual.topic_id)
        .outerjoin(Unit, Unit.id == Topic.unit_id)
        .where(has_content)
        .order_by(Visual.updated_at.desc(), Visual.id)
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(Visual.status == status)
    else:
        stmt = stmt.where(Visual.status.in_(WAITING_FOR_REVIEW), Visual.safety_passed.is_not(False))
    if unit_number is not None:
        stmt = stmt.where(Unit.number == unit_number)
    return [(v, t, u) for v, t, u in (await session.execute(stmt)).all()]


async def get_with_topic(
    session: AsyncSession, visual_id: uuid.UUID
) -> tuple[Visual, Topic | None, Unit | None] | None:
    row = (
        await session.execute(
            select(Visual, Topic, Unit)
            .outerjoin(Topic, Topic.id == Visual.topic_id)
            .outerjoin(Unit, Unit.id == Topic.unit_id)
            .where(Visual.id == visual_id)
        )
    ).first()
    return (row[0], row[1], row[2]) if row else None


async def waiting_for_review_counts(session: AsyncSession, older_than: datetime) -> tuple[int, int]:
    """For the dashboard: (finished visuals waiting for review, how many of them are older)."""
    has_content = or_(Visual.mermaid_code.is_not(None), Visual.image_path.is_not(None))
    result = await session.execute(
        select(func.count(), func.count().filter(Visual.created_at < older_than)).where(
            has_content,
            Visual.status.in_(WAITING_FOR_REVIEW),
            Visual.safety_passed.is_not(False),
        )
    )
    total, old = result.one()
    return int(total), int(old)


async def reports_per_day(session: AsyncSession, since: datetime) -> dict[date, int]:
    """{Sri Lanka date: visual reports made} - for the dashboard."""
    day = func.date(func.timezone("Asia/Colombo", VisualReport.created_at))
    result = await session.execute(
        select(day, func.count()).where(VisualReport.created_at >= since).group_by(day)
    )
    return {d: int(n) for d, n in result.all()}
