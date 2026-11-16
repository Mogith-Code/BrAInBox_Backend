"""All SQL queries for the community module. Owner: Mogith.

Tables: community_groups, group_members, posts, replies, votes, content_reports
Also writes `notifications` (moderation warnings) and reads `users` (author names).
Only this module's `service.py` may import this file.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    CommunityGroup,
    ContentReport,
    GroupMember,
    Notification,
    Post,
    Reply,
    Topic,
    Unit,
    User,
    Vote,
)
from shared.enums import ModerationStatus

GroupRef = uuid.UUID | str  # a group's UUID or its slug ("unit-6")


# ---------------------------------------------------------------- groups
async def list_visible_groups(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[CommunityGroup, str | None]]:
    """Groups the user may see, each with the user's role (None = not a member).

    Public groups are visible to everyone; a private group only to its members.
    """
    result = await session.execute(
        select(CommunityGroup, GroupMember.role)
        .outerjoin(
            GroupMember,
            and_(GroupMember.group_id == CommunityGroup.id, GroupMember.user_id == user_id),
        )
        .outerjoin(Unit, Unit.id == CommunityGroup.unit_id)
        .where(or_(CommunityGroup.is_private.is_(False), GroupMember.id.is_not(None)))
        # Default group first, then by unit NUMBER (so Unit 2 comes before Unit 10), then
        # groups without a unit by name.
        .order_by(
            CommunityGroup.is_default.desc(), Unit.number.asc().nulls_last(), CommunityGroup.name
        )
    )
    return [(group, role) for group, role in result.all()]


async def get_group(
    session: AsyncSession, ref: GroupRef, user_id: uuid.UUID
) -> tuple[CommunityGroup, str | None] | None:
    """One group by UUID or slug, with the user's role (None = not a member)."""
    match = CommunityGroup.id == ref if isinstance(ref, uuid.UUID) else CommunityGroup.slug == ref
    result = await session.execute(
        select(CommunityGroup, GroupMember.role)
        .outerjoin(
            GroupMember,
            and_(GroupMember.group_id == CommunityGroup.id, GroupMember.user_id == user_id),
        )
        .where(match)
        # member_count is changed with UPDATE statements; read the fresh value, not the copy
        # the session already holds.
        .execution_options(populate_existing=True)
    )
    row = result.first()
    return (row[0], row[1]) if row else None


async def add_member(session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Join. Returns True if the user was added, False if already a member. member_count is
    changed in the same statement batch, inside the database, so two taps can't miscount."""
    inserted = await session.scalar(
        insert(GroupMember)
        .values(group_id=group_id, user_id=user_id, role="member")
        .on_conflict_do_nothing(constraint="uq_group_members_group_user")
        .returning(GroupMember.id)
    )
    if inserted is None:
        return False
    await session.execute(
        update(CommunityGroup)
        .where(CommunityGroup.id == group_id)
        .values(member_count=CommunityGroup.member_count + 1)
    )
    return True


async def remove_member(session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Leave. Returns True if the user was removed, False if not a member."""
    removed = await session.scalar(
        delete(GroupMember)
        .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        .returning(GroupMember.id)
    )
    if removed is None:
        return False
    await session.execute(
        update(CommunityGroup)
        .where(CommunityGroup.id == group_id)
        .values(member_count=func.greatest(CommunityGroup.member_count - 1, 0))
    )
    return True


# ---------------------------------------------------------------- posts
PostSort = Literal["new", "top"]

# The author sees their own post while it is waiting or held for review; others don't.
_AUTHOR_ONLY_STATUSES = (ModerationStatus.PENDING, ModerationStatus.FLAGGED)


def _visible(model: Any, user_id: uuid.UUID) -> ColumnElement[bool]:
    """Not deleted, and approved (or the user's own pending / flagged one). Posts and replies."""
    return and_(
        model.deleted_at.is_(None),
        or_(
            model.moderation_status == ModerationStatus.APPROVED,
            and_(model.author_id == user_id, model.moderation_status.in_(_AUTHOR_ONLY_STATUSES)),
        ),
    )


@dataclass
class PostRow:
    post: Post
    author_name: str | None
    topic: str | None
    my_vote: int = 0  # the user's vote: 1, -1 or 0


def _post_query(user_id: uuid.UUID) -> Any:
    return (
        select(Post, User.display_name, Topic.title, func.coalesce(Vote.value, 0))
        .outerjoin(User, User.id == Post.author_id)
        .outerjoin(Topic, Topic.id == Post.topic_id)
        # at most one row: uq_votes_user_post
        .outerjoin(Vote, and_(Vote.post_id == Post.id, Vote.user_id == user_id))
        .where(_visible(Post, user_id))
    )


async def list_posts(
    session: AsyncSession,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    sort: PostSort,
    offset: int,
    limit: int,
) -> tuple[list[PostRow], int]:
    """One page of a group's visible posts, and how many there are in total."""
    stmt = _post_query(user_id).where(Post.group_id == group_id)
    total = await session.scalar(stmt.with_only_columns(func.count(Post.id)))
    order = (
        (Post.created_at.desc(), Post.id)
        if sort == "new"
        else (Post.score.desc(), Post.created_at.desc(), Post.id)
    )
    rows = await session.execute(stmt.order_by(*order).offset(offset).limit(limit))
    return [PostRow(*row) for row in rows.all()], total or 0


async def get_visible_post(
    session: AsyncSession, post_id: uuid.UUID, user_id: uuid.UUID
) -> PostRow | None:
    """A post the user may see, or None. Fresh values (score / reply_count change in SQL)."""
    result = await session.execute(
        _post_query(user_id).where(Post.id == post_id).execution_options(populate_existing=True)
    )
    row = result.first()
    return PostRow(*row) if row else None


async def add_post(session: AsyncSession, post: Post) -> None:
    session.add(post)
    await session.flush()


@dataclass
class ReplyRow:
    reply: Reply
    author_name: str | None
    my_vote: int = 0  # the user's vote: 1, -1 or 0


def _reply_query(user_id: uuid.UUID) -> Any:
    return (
        select(Reply, User.display_name, func.coalesce(Vote.value, 0))
        .outerjoin(User, User.id == Reply.author_id)
        # at most one row: uq_votes_user_reply
        .outerjoin(Vote, and_(Vote.reply_id == Reply.id, Vote.user_id == user_id))
        .where(_visible(Reply, user_id))
    )


async def list_replies(
    session: AsyncSession, post_id: uuid.UUID, user_id: uuid.UUID
) -> list[ReplyRow]:
    """A post's visible replies: the accepted answer first, then the highest score, then oldest."""
    result = await session.execute(
        _reply_query(user_id)
        .where(Reply.post_id == post_id)
        .order_by(Reply.is_accepted.desc(), Reply.score.desc(), Reply.created_at, Reply.id)
        .execution_options(populate_existing=True)  # is_accepted / score change in SQL
    )
    return [ReplyRow(*row) for row in result.all()]


async def get_visible_reply(
    session: AsyncSession, reply_id: uuid.UUID, user_id: uuid.UUID
) -> ReplyRow | None:
    """A reply the user may see, or None. Fresh values (is_accepted / score change in SQL)."""
    result = await session.execute(
        _reply_query(user_id).where(Reply.id == reply_id).execution_options(populate_existing=True)
    )
    row = result.first()
    return ReplyRow(*row) if row else None


async def add_reply(session: AsyncSession, reply: Reply) -> None:
    session.add(reply)
    await session.flush()


async def change_reply_count(session: AsyncSession, post_id: uuid.UUID, delta: int) -> None:
    """Add delta to the post's reply_count inside the database (never below 0)."""
    await session.execute(
        update(Post)
        .where(Post.id == post_id)
        .values(reply_count=func.greatest(Post.reply_count + delta, 0))
    )


async def set_accepted_reply(
    session: AsyncSession, post_id: uuid.UUID, reply_id: uuid.UUID | None
) -> None:
    """Make `reply_id` the post's only accepted reply (None = no accepted reply)."""
    await session.execute(
        update(Reply)
        .where(Reply.post_id == post_id, Reply.is_accepted.is_(True))
        .values(is_accepted=False)
    )
    if reply_id is not None:
        await session.execute(update(Reply).where(Reply.id == reply_id).values(is_accepted=True))
    await session.execute(update(Post).where(Post.id == post_id).values(accepted_reply_id=reply_id))


# ---------------------------------------------------------------- votes
Target = type[Post] | type[Reply]


async def lock_target(session: AsyncSession, model: Target, target_id: uuid.UUID) -> None:
    """Lock the post / reply row until commit, so votes on it are handled one at a time and
    its score can't miscount (two taps at the same moment)."""
    await session.execute(select(model.id).where(model.id == target_id).with_for_update())


async def get_vote(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    post_id: uuid.UUID | None,
    reply_id: uuid.UUID | None,
) -> Vote | None:
    stmt = select(Vote).where(Vote.user_id == user_id)
    stmt = stmt.where(Vote.post_id == post_id) if post_id else stmt.where(Vote.reply_id == reply_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def add_score(session: AsyncSession, model: Target, target_id: uuid.UUID, delta: int) -> int:
    """Add delta to the score inside the database and return the new score."""
    score = await session.scalar(
        update(model)
        .where(model.id == target_id)
        .values(score=model.score + delta)
        .returning(model.score)
    )
    return int(score or 0)


# ---------------------------------------------------------------- reports
async def has_open_report(
    session: AsyncSession, reporter_id: uuid.UUID, target_type: str, target_id: uuid.UUID
) -> bool:
    found = await session.scalar(
        select(ContentReport.id).where(
            ContentReport.reporter_id == reporter_id,
            ContentReport.target_type == target_type,
            ContentReport.target_id == target_id,
            ContentReport.status == ModerationStatus.PENDING,
        )
    )
    return found is not None


async def add_report(session: AsyncSession, report: ContentReport) -> None:
    session.add(report)
    await session.flush()


async def count_open_reporters(
    session: AsyncSession, target_type: str, target_id: uuid.UUID
) -> int:
    """How many different people have an open report on this post / reply."""
    result = await session.scalar(
        select(func.count(func.distinct(ContentReport.reporter_id))).where(
            ContentReport.target_type == target_type,
            ContentReport.target_id == target_id,
            ContentReport.status == ModerationStatus.PENDING,
        )
    )
    return result or 0


async def flag_if_approved(session: AsyncSession, model: Target, target_id: uuid.UUID) -> bool:
    """Hide an approved post / reply for review (flagged). Returns True if it was approved."""
    flagged = await session.scalar(
        update(model)
        .where(model.id == target_id, model.moderation_status == ModerationStatus.APPROVED)
        .values(moderation_status=ModerationStatus.FLAGGED)
        .returning(model.id)
    )
    return flagged is not None


# =========================================================================== admin side
# Used by the admin moderation pages (admin/moderation_admin.py). Note: `get_post` /
# `get_reply` / `list_groups` below are the ADMIN versions (no visibility rules); the student
# routes above use `get_visible_post` / `get_visible_reply` / `list_visible_groups`.


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
