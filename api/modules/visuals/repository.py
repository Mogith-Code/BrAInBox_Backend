"""All SQL queries for the visuals module. Owner: Mogith.

Tables: visuals, visual_reports
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AIJob, Visual, VisualReport
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


async def list_reports(
    session: AsyncSession, status: ModerationStatus, limit: int
) -> list[tuple[VisualReport, Visual]]:
    """Reports with their visual, oldest first (the queue order)."""
    result = await session.execute(
        select(VisualReport, Visual)
        .join(Visual, Visual.id == VisualReport.visual_id)
        .where(VisualReport.status == status)
        .order_by(VisualReport.created_at, VisualReport.id)
        .limit(limit)
    )
    return [(report, visual) for report, visual in result.all()]
