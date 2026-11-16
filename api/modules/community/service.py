"""Business logic for the community module. Owner: Mogith.

Student side (community/router.py):
Groups: every student sees the public groups ("General" first, then one per unit) and can join
or leave them. A private group is only visible to its members and can't be joined from the app.

Posts and replies: anyone who can see a group can read them; only members can post or reply.
Only the author can edit; the author or an admin can delete (soft delete). The post's author
picks the accepted answer. New posts and replies are published straight away for now
(NEW_CONTENT_STATUS); AI moderation will switch that to "pending".

Admin side (admin/moderation_admin.py):
  * Moderation queue: open reports of posts and replies (`content_reports`) and of visuals
    (visuals module), one item per reported target, oldest first.
  * Resolve: keep (dismiss the reports) | warn (tell the author + dismiss) | remove (hide the
    post / reply / visual + resolve). Every open report of that target is closed at once.
  * Study groups: list (members, moderator) and create.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import re
import uuid
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from api.core.pagination import Page, PageParams
from api.core.security import CurrentUser
from api.modules.community import repository
from api.modules.community.repository import GroupRef, PostRow, PostSort, ReplyRow
from api.modules.community.schemas import (
    AuthorOut,
    GroupCreate,
    GroupOut,
    ModerationAction,
    ModerationItemOut,
    ModuleStatus,
    PostCreate,
    PostDetailOut,
    PostOut,
    PostUpdate,
    ReplyCreate,
    ReplyOut,
    ReplyUpdate,
    ReportIn,
    ReportOut,
    StudyGroupOut,
    VoteIn,
    VoteOut,
)
from api.modules.syllabus import service as syllabus_service
from api.modules.visuals import service as visuals_service
from shared.db.models import CommunityGroup, ContentReport, Notification, Post, Reply, Vote
from shared.enums import ModerationStatus, NotificationType

MODULE_NAME = "community"
TEXT_PREVIEW_CHARS = 500

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


def group_out(group: CommunityGroup, role: str | None) -> StudyGroupOut:
    return StudyGroupOut(
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


async def list_visible_groups(session: AsyncSession, user: CurrentUser) -> list[StudyGroupOut]:
    """GET /groups: General first, then the unit groups in order."""
    return [
        group_out(g, role) for g, role in await repository.list_visible_groups(session, user.id)
    ]


async def get_group(session: AsyncSession, user: CurrentUser, group_ref: str) -> StudyGroupOut:
    """GET /groups/{id}"""
    return group_out(*await _visible_group(session, user, group_ref))


async def join_group(session: AsyncSession, user: CurrentUser, group_ref: str) -> StudyGroupOut:
    """POST /groups/{id}/join. Joining again changes nothing. Private groups are hidden from
    non-members (404), so they can't be joined from here."""
    group, _ = await _visible_group(session, user, group_ref)
    await repository.add_member(session, group.id, user.id)
    await session.commit()
    return group_out(*await _visible_group(session, user, group_ref))


async def leave_group(session: AsyncSession, user: CurrentUser, group_ref: str) -> StudyGroupOut:
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
    row = await repository.get_visible_post(session, post_id, user.id)
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
    row = await repository.get_visible_reply(session, reply_id, user.id)
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
    """The visible post or reply being voted on / reported, and the post it belongs to."""
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


# =========================================================================== reports


async def report(
    session: AsyncSession,
    user: CurrentUser,
    req: ReportIn,
    *,
    post_id: uuid.UUID | None = None,
    reply_id: uuid.UUID | None = None,
) -> ReportOut:
    """POST /posts/{id}/report or /replies/{id}/report. One open report per person per post or
    reply (409 ALREADY_REPORTED); not on my own content (400 CANNOT_REPORT_OWN). When
    REPORTS_TO_HIDE different people have reported it, it is hidden (flagged) for review."""
    target, _ = await _target(session, user, post_id=post_id, reply_id=reply_id)
    if target.author_id == user.id:
        raise AppError("You can't report your own post or reply", code="CANNOT_REPORT_OWN")
    target_type = "post" if post_id else "reply"
    if await repository.has_open_report(session, user.id, target_type, target.id):
        raise ConflictError(
            "You already reported this. A moderator will look at it soon.",
            code="ALREADY_REPORTED",
        )
    report_row = ContentReport(
        reporter_id=user.id,
        target_type=target_type,
        target_id=target.id,
        reason=req.reason.value,
        details=(req.details or "").strip() or None,
    )
    await repository.add_report(session, report_row)

    reporters = await repository.count_open_reporters(session, target_type, target.id)
    if REPORTS_TO_HIDE and reporters >= REPORTS_TO_HIDE:
        model: type[Post] | type[Reply] = Post if post_id else Reply
        hidden = await repository.flag_if_approved(session, model, target.id)
        if hidden and isinstance(target, Reply):  # a hidden reply no longer counts
            await repository.change_reply_count(session, target.post_id, -1)
    await session.commit()
    return ReportOut(
        id=report_row.id,
        target_type=target_type,
        target_id=target.id,
        reason=req.reason,
        status=report_row.status,
        created_at=report_row.created_at,
    )


# =========================================================================== admin side
# TODO(Mogith): auto-tag via ai_client.sync('tag-post'); MODERATE_POST fills
#   moderation_reason / _score.


def _score(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


# =========================================================================== moderation queue


async def moderation_queue(session: AsyncSession, base_url: str) -> list[ModerationItemOut]:
    """Every open report, one item per post / reply / visual, oldest first."""
    groups = await repository.open_report_groups(session)
    posts = await repository.posts_by_id(
        session, [r.target_id for r, _ in groups if r.target_type == "post"]
    )
    replies = await repository.replies_by_id(
        session, [r.target_id for r, _ in groups if r.target_type == "reply"]
    )
    # A reply's group is its post's group.
    posts.update(await repository.posts_by_id(session, [r.post_id for r in replies.values()]))
    group_names = await repository.group_names(
        session, [p.group_id for p in posts.values() if p.group_id]
    )
    authors = await repository.user_names(
        session,
        [p.author_id for p in posts.values() if p.author_id]
        + [r.author_id for r in replies.values() if r.author_id],
    )

    items: list[ModerationItemOut] = []
    for report, count in groups:
        if report.target_type == "post":
            post = posts.get(report.target_id)
            if post is None:
                continue  # deleted since; nothing left to moderate
            target_author, group_id = post.author_id, post.group_id
            text = f"{post.title}\n\n{post.body}".strip()
            label, score = post.moderation_reason, post.moderation_score
        else:
            reply = replies.get(report.target_id)
            if reply is None:
                continue
            parent = posts.get(reply.post_id)
            target_author, group_id = reply.author_id, parent.group_id if parent else None
            text = reply.body
            label, score = reply.moderation_reason, reply.moderation_score
        items.append(
            ModerationItemOut(
                id=report.id,
                target_type=report.target_type,  # type: ignore[arg-type]
                target_id=report.target_id,
                reason=report.reason,
                details=report.details,
                author_handle=authors.get(target_author) if target_author else None,
                group_name=group_names.get(group_id) if group_id else None,
                text=text[:TEXT_PREVIEW_CHARS],
                ai_flag_label=label,
                ai_flag_score=_score(score),
                report_count=count,
                created_at=report.created_at,
            )
        )
    items.extend(await visuals_service.moderation_items(session, base_url))
    items.sort(key=lambda i: (i.created_at, str(i.id)))
    return items


async def _warn(
    session: AsyncSession, user_id: uuid.UUID, what: str, reason: str, report_id: uuid.UUID
) -> None:
    """In-app notification for the author of content a moderator kept but warned about."""
    await repository.add_notification(
        session,
        Notification(
            user_id=user_id,
            type=NotificationType.SYSTEM,
            title=f"A moderator reviewed your {what}",
            body=(
                f"It was reported as '{reason.replace('_', ' ')}'. "
                "Please follow the community rules."
            ),
            data={"kind": "moderation_warning", "report_id": str(report_id)},
        ),
    )


async def resolve_report(
    session: AsyncSession, admin_id: uuid.UUID, report_id: uuid.UUID, action: ModerationAction
) -> str:
    """Resolve every open report of the reported target. Returns the target type.

    404 REPORT_NOT_FOUND · 409 REPORT_ALREADY_RESOLVED."""
    report = await repository.get_report(session, report_id)
    if report is None:
        visual = await visuals_service.resolve_report(session, report_id, action, admin_id)
        if visual is None:
            raise NotFoundError("Report not found", code="REPORT_NOT_FOUND")
        author_id, reason = visual
        if action == "warn" and author_id is not None:
            await _warn(session, author_id, "visual", reason, report_id)
        await session.commit()
        return "visual"

    if report.status != ModerationStatus.PENDING:
        raise ConflictError("This report was already resolved", code="REPORT_ALREADY_RESOLVED")
    target = (
        await repository.get_post(session, report.target_id)
        if report.target_type == "post"
        else await repository.get_reply(session, report.target_id)
    )
    now = clock.now()
    new_status = ModerationStatus.REMOVED if action == "remove" else ModerationStatus.APPROVED
    for row in await repository.pending_reports_of(session, report.target_type, report.target_id):
        row.status = new_status
        row.reviewed_by = admin_id
        row.resolved_at = now
    if target is not None:
        was_visible = target.moderation_status == ModerationStatus.APPROVED
        if action == "remove":
            target.moderation_status = ModerationStatus.REMOVED  # hidden from students
        elif target.moderation_status == ModerationStatus.FLAGGED:
            # keep / warn: content hidden by the "3 reports" safety net (see report()) is
            # shown again.
            target.moderation_status = ModerationStatus.APPROVED
        if action == "warn" and target.author_id is not None:
            await _warn(session, target.author_id, report.target_type, report.reason, report.id)
        # reply_count only counts visible replies: fix it when a reply is hidden or shown again.
        if isinstance(target, Reply):
            is_visible = target.moderation_status == ModerationStatus.APPROVED
            if was_visible != is_visible:
                await repository.change_reply_count(
                    session, target.post_id, +1 if is_visible else -1
                )
    await session.commit()
    return report.target_type


# =========================================================================== study groups


def _group_out(group: CommunityGroup, members: int, moderator: str | None) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        members=members,
        moderator_name=moderator,
        is_open=not group.is_private,
    )


async def list_groups(session: AsyncSession) -> list[GroupOut]:
    return [_group_out(g, n, m) for g, n, m in await repository.list_groups(session)]


def slugify(name: str) -> str:
    """ "Unit 6 · Genetics" -> "unit-6-genetics" """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:90] or "group"


async def create_group(session: AsyncSession, admin_id: uuid.UUID, req: GroupCreate) -> GroupOut:
    """409 GROUP_NAME_TAKEN when a group already has this name (any case)."""
    if await repository.group_name_taken(session, req.name):
        raise ConflictError(f"A group called '{req.name}' already exists", code="GROUP_NAME_TAKEN")
    slug, n = slugify(req.name), 2
    while await repository.slug_taken(session, slug):
        slug, n = f"{slugify(req.name)}-{n}", n + 1
    group = CommunityGroup(
        id=uuid.uuid4(),
        name=req.name,
        slug=slug,
        is_private=False,
        is_default=False,
        member_count=0,
        created_by=admin_id,
    )
    await repository.add_group(session, group)
    await session.commit()
    return _group_out(group, 0, None)


async def reports_per_day(session: AsyncSession, since: datetime) -> dict[date, int]:
    """All new reports per day (posts, replies, visuals) - for the admin dashboard."""
    counts = await repository.reports_per_day(session, since)
    for day, n in (await visuals_service.reports_per_day(session, since)).items():
        counts[day] = counts.get(day, 0) + n
    return counts
