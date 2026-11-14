"""All SQL queries for the community module. Owner: Mogith.

Tables: community_groups, group_members, posts, replies, votes, content_reports
Only this module's `service.py` may import this file.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import CommunityGroup, GroupMember, Post, Reply, Topic, Unit, User
from shared.enums import ModerationStatus

GroupRef = uuid.UUID | str  # a group's UUID or its slug ("unit-6")


# ---------------------------------------------------------------- groups
async def list_groups(
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


def _post_query(user_id: uuid.UUID) -> Any:
    return (
        select(Post, User.display_name, Topic.title)
        .outerjoin(User, User.id == Post.author_id)
        .outerjoin(Topic, Topic.id == Post.topic_id)
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


async def get_post(session: AsyncSession, post_id: uuid.UUID, user_id: uuid.UUID) -> PostRow | None:
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


async def list_replies(
    session: AsyncSession, post_id: uuid.UUID, user_id: uuid.UUID
) -> list[ReplyRow]:
    """A post's visible replies: the accepted answer first, then the highest score, then oldest."""
    result = await session.execute(
        select(Reply, User.display_name)
        .outerjoin(User, User.id == Reply.author_id)
        .where(Reply.post_id == post_id, _visible(Reply, user_id))
        .order_by(Reply.is_accepted.desc(), Reply.score.desc(), Reply.created_at, Reply.id)
    )
    return [ReplyRow(*row) for row in result.all()]
