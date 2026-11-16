"""Business logic for the community module. Owner: Mogith.

Groups: every student sees the public groups ("General" first, then one per unit) and can join
or leave them. A private group is only visible to its members and can't be joined from the app.

Posts and replies: anyone who can see a group can read them; only members can post or reply.
Only the author can edit; the author or an admin can delete (soft delete). The post's author
picks the accepted answer. New posts and replies are published straight away for now
(NEW_CONTENT_STATUS); AI moderation will switch that to "pending".

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
    ReplyCreate,
    ReplyOut,
    ReplyUpdate,
    VoteIn,
    VoteOut,
)
from api.modules.syllabus import service as syllabus_service
from shared.db.models import CommunityGroup, Post, Reply, Vote
from shared.enums import ModerationStatus

MODULE_NAME = "community"

# Decision (option A): publish new posts and replies straight away and rely on reports. When AI
# moderation (MODERATE_POST) is added, change this to ModerationStatus.PENDING - and only count a
# reply in the post's reply_count once it is approved.
NEW_CONTENT_STATUS = ModerationStatus.APPROVED
# Safety net while there is no review before publishing: a post / reply reported by this many
# different people is hidden (flagged) until an admin decides. 0 turns it off.
REPORTS_TO_HIDE = 3
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
        my_vote=row.my_vote,
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
        my_vote=row.my_vote,
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
        moderation_status=NEW_CONTENT_STATUS,
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


# =========================================================================== replies


async def _require_member(session: AsyncSession, user: CurrentUser, post: Post) -> None:
    """Only members of the post's group may reply (403 NOT_A_MEMBER)."""
    if post.group_id is None:
        return
    group_row = await repository.get_group(session, post.group_id, user.id)
    if group_row is None or group_row[1] is None:
        raise ForbiddenError("Join the group to reply", code="NOT_A_MEMBER")


async def _visible_reply(session: AsyncSession, user: CurrentUser, reply_id: uuid.UUID) -> ReplyRow:
    """A reply the user may see, on a post the user may see, or 404 REPLY_NOT_FOUND."""
    row = await repository.get_reply(session, reply_id, user.id)
    if row is None:
        raise NotFoundError("Reply not found", code="REPLY_NOT_FOUND")
    try:
        await _visible_post(session, user, row.reply.post_id)
    except NotFoundError as exc:  # the post was deleted, or its group is private
        raise NotFoundError("Reply not found", code="REPLY_NOT_FOUND") from exc
    return row


async def create_reply(
    session: AsyncSession, user: CurrentUser, post_id: uuid.UUID, req: ReplyCreate
) -> ReplyOut:
    """POST /posts/{id}/replies. Members of the post's group only."""
    post = (await _visible_post(session, user, post_id)).post
    await _require_member(session, user, post)
    reply = Reply(
        post_id=post.id,
        author_id=user.id,
        body=req.body.strip(),
        moderation_status=NEW_CONTENT_STATUS,
    )
    await repository.add_reply(session, reply)
    if reply.moderation_status == ModerationStatus.APPROVED:  # only visible replies are counted
        await repository.change_reply_count(session, post.id, +1)
    await session.commit()
    return reply_out(await _visible_reply(session, user, reply.id), user)


async def update_reply(
    session: AsyncSession, user: CurrentUser, reply_id: uuid.UUID, req: ReplyUpdate
) -> ReplyOut:
    """PATCH /replies/{id}: only the author (403 NOT_REPLY_AUTHOR)."""
    row = await _visible_reply(session, user, reply_id)
    if row.reply.author_id != user.id:
        raise ForbiddenError("Only the author can edit this reply", code="NOT_REPLY_AUTHOR")
    row.reply.body = req.body.strip()
    await session.commit()
    return reply_out(await _visible_reply(session, user, reply_id), user)


async def delete_reply(session: AsyncSession, user: CurrentUser, reply_id: uuid.UUID) -> None:
    """DELETE /replies/{id}: the author or an admin (soft delete). A deleted accepted answer is
    no longer accepted, and the post's reply_count goes down."""
    reply = (await _visible_reply(session, user, reply_id)).reply
    if reply.author_id != user.id and not user.is_admin:
        raise ForbiddenError("Only the author can delete this reply", code="NOT_REPLY_AUTHOR")
    if reply.is_accepted:
        await repository.set_accepted_reply(session, reply.post_id, None)
    if reply.moderation_status == ModerationStatus.APPROVED:
        await repository.change_reply_count(session, reply.post_id, -1)
    reply.deleted_at = clock.now()
    await session.commit()


async def accept_reply(
    session: AsyncSession, user: CurrentUser, post_id: uuid.UUID, reply_id: uuid.UUID | None
) -> PostDetailOut:
    """POST /posts/{id}/accept/{reply_id} (or DELETE /posts/{id}/accept with reply_id=None).
    Only the post's author (403 NOT_POST_AUTHOR). The reply must be a visible reply of this
    post (404 REPLY_NOT_FOUND). Accepting another reply replaces the old one."""
    post = (await _visible_post(session, user, post_id)).post
    if post.author_id != user.id:
        raise ForbiddenError("Only the post's author can accept an answer", code="NOT_POST_AUTHOR")
    if reply_id is not None:
        reply = (await _visible_reply(session, user, reply_id)).reply
        if reply.post_id != post.id or reply.moderation_status != ModerationStatus.APPROVED:
            raise NotFoundError("Reply not found", code="REPLY_NOT_FOUND")
    await repository.set_accepted_reply(session, post.id, reply_id)
    await session.commit()
    return await get_post(session, user, post_id)


# =========================================================================== votes


async def _target(
    session: AsyncSession,
    user: CurrentUser,
    *,
    post_id: uuid.UUID | None,
    reply_id: uuid.UUID | None,
) -> tuple[Post | Reply, Post]:
    """The visible post or reply being voted on, and the post it belongs to."""
    if post_id is not None:
        post = (await _visible_post(session, user, post_id)).post
        return post, post
    assert reply_id is not None
    reply = (await _visible_reply(session, user, reply_id)).reply
    return reply, (await _visible_post(session, user, reply.post_id)).post


async def vote(session: AsyncSession, user: CurrentUser, req: VoteIn) -> VoteOut:
    """POST /votes: +1 / -1 on a post or reply, 0 removes my vote. Voting again changes my vote
    (the score moves by the difference). Members only, never on my own post or reply."""
    target, post = await _target(session, user, post_id=req.post_id, reply_id=req.reply_id)
    if target.author_id == user.id:
        raise ForbiddenError("You can't vote on your own post or reply", code="CANNOT_VOTE_OWN")
    await _require_member(session, user, post)
    model: type[Post] | type[Reply] = Post if req.post_id else Reply

    await repository.lock_target(session, model, target.id)  # one vote at a time on it
    existing = await repository.get_vote(
        session, user.id, post_id=req.post_id, reply_id=req.reply_id
    )
    old = existing.value if existing else 0
    if req.value == 0:
        if existing is not None:
            await session.delete(existing)
    elif existing is not None:
        existing.value = req.value
    else:
        session.add(
            Vote(user_id=user.id, post_id=req.post_id, reply_id=req.reply_id, value=req.value)
        )
    await session.flush()
    score = await repository.add_score(session, model, target.id, req.value - old)
    await session.commit()
    return VoteOut(
        target_type="post" if req.post_id else "reply",
        target_id=target.id,
        my_vote=req.value,
        score=score,
    )
