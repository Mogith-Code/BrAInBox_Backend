"""All SQL queries for the community module. Owner: Mogith.

Tables: community_groups, group_members, posts, replies, votes, content_reports
Also writes `notifications` (moderation warnings) and reads `users` (author names).
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    CommunityGroup,
    ContentReport,
    GroupMember,
    Notification,
    Post,
    Reply,
    User,
)
from shared.enums import ModerationStatus


async def count_community_groups(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(CommunityGroup))
    return result.scalar_one()


# ---------------------------------------------------------------- reports (admin moderation)
async def open_report_groups(session: AsyncSession) -> list[tuple[ContentReport, int]]:
    """Pending post / reply reports, one per target: (the oldest report, how many). Oldest first."""
    counts = (
        select(
            ContentReport.target_type,
            ContentReport.target_id,
            func.count().label("n"),
            func.min(ContentReport.created_at).label("first_at"),
        )
        .where(ContentReport.status == ModerationStatus.PENDING)
        .group_by(ContentReport.target_type, ContentReport.target_id)
        .subquery()
    )
    result = await session.execute(
        select(ContentReport, counts.c.n)
        .join(
            counts,
            (counts.c.target_type == ContentReport.target_type)
            & (counts.c.target_id == ContentReport.target_id)
            & (counts.c.first_at == ContentReport.created_at),
        )
        .where(ContentReport.status == ModerationStatus.PENDING)
        .order_by(ContentReport.created_at, ContentReport.id)
    )
    seen: set[tuple[str, uuid.UUID]] = set()
    rows = []
    for report, n in result.all():
        key = (report.target_type, report.target_id)
        if key not in seen:  # two reports at the very same moment: keep one
            seen.add(key)
            rows.append((report, int(n)))
    return rows


async def get_report(session: AsyncSession, report_id: uuid.UUID) -> ContentReport | None:
    return await session.get(ContentReport, report_id)


async def pending_reports_of(
    session: AsyncSession, target_type: str, target_id: uuid.UUID
) -> list[ContentReport]:
    result = await session.execute(
        select(ContentReport).where(
            ContentReport.target_type == target_type,
            ContentReport.target_id == target_id,
            ContentReport.status == ModerationStatus.PENDING,
        )
    )
    return list(result.scalars())


async def posts_by_id(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, Post]:
    if not ids:
        return {}
    result = await session.execute(select(Post).where(Post.id.in_(ids)))
    return {p.id: p for p in result.scalars()}


async def replies_by_id(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, Reply]:
    if not ids:
        return {}
    result = await session.execute(select(Reply).where(Reply.id.in_(ids)))
    return {r.id: r for r in result.scalars()}


async def group_names(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    result = await session.execute(
        select(CommunityGroup.id, CommunityGroup.name).where(CommunityGroup.id.in_(ids))
    )
    return {key: value for key, value in result.all()}


async def user_names(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    if not ids:
        return {}
    result = await session.execute(select(User.id, User.display_name).where(User.id.in_(ids)))
    return {key: value for key, value in result.all()}


async def get_post(session: AsyncSession, post_id: uuid.UUID) -> Post | None:
    return await session.get(Post, post_id)


async def get_reply(session: AsyncSession, reply_id: uuid.UUID) -> Reply | None:
    return await session.get(Reply, reply_id)


async def add_notification(session: AsyncSession, notification: Notification) -> None:
    session.add(notification)
    await session.flush()


# ---------------------------------------------------------------- groups (admin)
async def list_groups(session: AsyncSession) -> list[tuple[CommunityGroup, int, str | None]]:
    """(group, members, the first moderator's name) for every group, by name."""
    members = (
        select(GroupMember.group_id, func.count().label("n"))
        .group_by(GroupMember.group_id)
        .subquery()
    )
    moderator = (
        select(GroupMember.group_id, func.min(User.display_name).label("name"))
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.role == "moderator")
        .group_by(GroupMember.group_id)
        .subquery()
    )
    result = await session.execute(
        select(CommunityGroup, func.coalesce(members.c.n, 0), moderator.c.name)
        .outerjoin(members, members.c.group_id == CommunityGroup.id)
        .outerjoin(moderator, moderator.c.group_id == CommunityGroup.id)
        .order_by(func.lower(CommunityGroup.name), CommunityGroup.id)
    )
    return [(g, int(n), name) for g, n, name in result.all()]


async def group_name_taken(session: AsyncSession, name: str) -> bool:
    result = await session.execute(
        select(CommunityGroup.id).where(func.lower(CommunityGroup.name) == name.lower()).limit(1)
    )
    return result.first() is not None


async def slug_taken(session: AsyncSession, slug: str) -> bool:
    result = await session.execute(
        select(CommunityGroup.id).where(CommunityGroup.slug == slug).limit(1)
    )
    return result.first() is not None


async def add_group(session: AsyncSession, group: CommunityGroup) -> None:
    session.add(group)
    await session.flush()


async def reports_per_day(session: AsyncSession, since: datetime) -> dict[date, int]:
    """{Sri Lanka date: post / reply reports made} - for the dashboard."""
    day = func.date(func.timezone("Asia/Colombo", ContentReport.created_at))
    result = await session.execute(
        select(day, func.count()).where(ContentReport.created_at >= since).group_by(day)
    )
    return {d: int(n) for d, n in result.all()}
