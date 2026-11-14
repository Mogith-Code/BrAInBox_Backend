"""Business logic for the community module. Owner: Mogith.

Groups: every student sees the public groups ("General" first, then one per unit) and can join
or leave them. A private group is only visible to its members and can't be joined from the app.

Posts: anyone who can see a group can read its posts; only members can post. Only the author
can edit; the author or an admin can delete (soft delete). New posts are published straight
away for now (NEW_POST_STATUS); AI moderation will switch that to "pending".

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.core.errors import AppError, ForbiddenError, NotFoundError
from api.core.pagination import Page, PageParams
from api.core.security import CurrentUser
from api.modules.community import repository
from api.modules.community.repository import GroupRef, PostRow, PostSort, ReplyRow
from api.modules.community.schemas import (
    AuthorOut,
    GroupOut,
    ModuleStatus,
    PostCreate,
    PostDetailOut,
    PostOut,
    PostUpdate,
    ReplyOut,
)
from api.modules.syllabus import service as syllabus_service
from shared.db.models import CommunityGroup, Post
from shared.enums import ModerationStatus

MODULE_NAME = "community"

# Decision (option A): publish new posts straight away and rely on reports. When AI moderation
# (MODERATE_POST) is added, change this to ModerationStatus.PENDING.
NEW_POST_STATUS = ModerationStatus.APPROVED
UNNAMED_AUTHOR = "Student"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# =========================================================================== groups


def parse_group_ref(value: str) -> GroupRef:
    """A path parameter is either a group's UUID or its slug ("unit-6")."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return value


def group_out(group: CommunityGroup, role: str | None) -> GroupOut:
    return GroupOut(
        id=group.id,
        slug=group.slug,
        name=group.name,
        description=group.description,
        unit_id=group.unit_id,
        is_default=group.is_default,
        is_private=group.is_private,
        member_count=group.member_count,
        is_member=role is not None,
        my_role=role,
    )


async def _visible_group(
    session: AsyncSession, user: CurrentUser, group_ref: str
) -> tuple[CommunityGroup, str | None]:
    """The group, or 404 GROUP_NOT_FOUND. A private group the user isn't in is "not found" too,
    so its existence isn't leaked."""
    row = await repository.get_group(session, parse_group_ref(group_ref), user.id)
    if row is None or (row[0].is_private and row[1] is None):
        raise NotFoundError("Group not found", code="GROUP_NOT_FOUND")
    return row


async def list_groups(session: AsyncSession, user: CurrentUser) -> list[GroupOut]:
    """GET /groups: General first, then the unit groups in order."""
    return [group_out(g, role) for g, role in await repository.list_groups(session, user.id)]


async def get_group(session: AsyncSession, user: CurrentUser, group_ref: str) -> GroupOut:
    """GET /groups/{id}"""
    return group_out(*await _visible_group(session, user, group_ref))


async def join_group(session: AsyncSession, user: CurrentUser, group_ref: str) -> GroupOut:
    """POST /groups/{id}/join. Joining again changes nothing. Private groups are hidden from
    non-members (404), so they can't be joined from here."""
    group, _ = await _visible_group(session, user, group_ref)
    await repository.add_member(session, group.id, user.id)
    await session.commit()
    return group_out(*await _visible_group(session, user, group_ref))


async def leave_group(session: AsyncSession, user: CurrentUser, group_ref: str) -> GroupOut:
    """DELETE /groups/{id}/join. Leaving a group you're not in changes nothing."""
    group, _ = await _visible_group(session, user, group_ref)
    await repository.remove_member(session, group.id, user.id)
    await session.commit()
    return group_out(*await _visible_group(session, user, group_ref))


# =========================================================================== posts


def _author(author_id: uuid.UUID | None, name: str | None) -> AuthorOut | None:
    return AuthorOut(id=author_id, name=name or UNNAMED_AUTHOR) if author_id else None


def post_out(row: PostRow, user: CurrentUser) -> PostOut:
    post = row.post
    return PostOut(
        id=post.id,
        group_id=post.group_id,
        title=post.title,
        body=post.body,
        tags=list(post.tags or []),
        topic_id=post.topic_id,
        topic=row.topic,
        unit_id=post.unit_id,
        is_question=post.is_question,
        author=_author(post.author_id, row.author_name),
        is_mine=post.author_id == user.id,
        moderation_status=post.moderation_status,
        score=post.score,
        reply_count=post.reply_count,
        accepted_reply_id=post.accepted_reply_id,
        created_at=post.created_at,
    )


def reply_out(row: ReplyRow, user: CurrentUser) -> ReplyOut:
    reply = row.reply
    return ReplyOut(
        id=reply.id,
        body=reply.body,
        author=_author(reply.author_id, row.author_name),
        is_mine=reply.author_id == user.id,
        is_ai_suggested=reply.is_ai_suggested,
        is_accepted=reply.is_accepted,
        moderation_status=reply.moderation_status,
        score=reply.score,
        created_at=reply.created_at,
    )


async def _check_topic(
    session: AsyncSession, topic_id: uuid.UUID, group_unit_id: uuid.UUID | None
) -> uuid.UUID:
    """The topic must exist (404 TOPIC_NOT_FOUND) and, in a unit group, belong to that unit.
    Returns the topic's unit."""
    [topic] = await syllabus_service.get_topics(session, [topic_id])
    if group_unit_id is not None and topic.unit_id != group_unit_id:
        raise AppError("This topic is from another unit", code="TOPIC_NOT_IN_GROUP_UNIT")
    return topic.unit_id


async def _visible_post(session: AsyncSession, user: CurrentUser, post_id: uuid.UUID) -> PostRow:
    """A post the user may see (its group too), or 404 POST_NOT_FOUND."""
    row = await repository.get_post(session, post_id, user.id)
    if row is None:
        raise NotFoundError("Post not found", code="POST_NOT_FOUND")
    if row.post.group_id is not None:
        group_row = await repository.get_group(session, row.post.group_id, user.id)
        if group_row is None or (group_row[0].is_private and group_row[1] is None):
            raise NotFoundError("Post not found", code="POST_NOT_FOUND")
    return row


async def list_posts(
    session: AsyncSession, user: CurrentUser, group_ref: str, sort: PostSort, paging: PageParams
) -> Page[PostOut]:
    """GET /groups/{id}/posts: newest first, or highest score first (`top`)."""
    group, _ = await _visible_group(session, user, group_ref)
    rows, total = await repository.list_posts(
        session, group.id, user.id, sort=sort, offset=paging.offset, limit=paging.size
    )
    return Page.create([post_out(r, user) for r in rows], total, paging)


async def create_post(
    session: AsyncSession, user: CurrentUser, group_ref: str, req: PostCreate
) -> PostOut:
    """POST /groups/{id}/posts. Members only (403 NOT_A_MEMBER)."""
    group, role = await _visible_group(session, user, group_ref)
    if role is None:
        raise ForbiddenError("Join the group to post in it", code="NOT_A_MEMBER")
    unit_id = group.unit_id
    if req.topic_id is not None:
        unit_id = await _check_topic(session, req.topic_id, group.unit_id)
    post = Post(
        group_id=group.id,
        author_id=user.id,
        unit_id=unit_id,
        topic_id=req.topic_id,
        title=req.title.strip(),
        body=req.body.strip(),
        tags=req.tags,
        is_question=req.is_question,
        moderation_status=NEW_POST_STATUS,
    )
    await repository.add_post(session, post)
    await session.commit()
    return post_out(await _visible_post(session, user, post.id), user)


async def get_post(session: AsyncSession, user: CurrentUser, post_id: uuid.UUID) -> PostDetailOut:
    """GET /posts/{id}: the post with its visible replies."""
    row = await _visible_post(session, user, post_id)
    replies = await repository.list_replies(session, post_id, user.id)
    return PostDetailOut(
        **post_out(row, user).model_dump(), replies=[reply_out(r, user) for r in replies]
    )


async def update_post(
    session: AsyncSession, user: CurrentUser, post_id: uuid.UUID, req: PostUpdate
) -> PostOut:
    """PATCH /posts/{id}: only the author (403 NOT_POST_AUTHOR). Send only fields to change."""
    row = await _visible_post(session, user, post_id)
    post = row.post
    if post.author_id != user.id:
        raise ForbiddenError("Only the author can edit this post", code="NOT_POST_AUTHOR")
    fields = req.model_fields_set
    for name in ("title", "body"):
        if name in fields:
            value = getattr(req, name)
            if value is None:
                raise AppError(f"{name} cannot be empty", code="FIELD_REQUIRED")
            setattr(post, name, value.strip())
    if "tags" in fields:
        post.tags = req.tags or []
    if "topic_id" in fields:
        if req.topic_id is None:
            post.topic_id = None
        else:
            group_unit_id = None
            if post.group_id is not None:
                group_row = await repository.get_group(session, post.group_id, user.id)
                group_unit_id = group_row[0].unit_id if group_row else None
            post.unit_id = await _check_topic(session, req.topic_id, group_unit_id)
            post.topic_id = req.topic_id
    await session.commit()
    return post_out(await _visible_post(session, user, post_id), user)


async def delete_post(session: AsyncSession, user: CurrentUser, post_id: uuid.UUID) -> None:
    """DELETE /posts/{id}: the author or an admin (403 NOT_POST_AUTHOR). Soft delete: the row
    stays (replies and votes keep working) but nobody sees it any more."""
    row = await _visible_post(session, user, post_id)
    if row.post.author_id != user.id and not user.is_admin:
        raise ForbiddenError("Only the author can delete this post", code="NOT_POST_AUTHOR")
    row.post.deleted_at = clock.now()
    await session.commit()
