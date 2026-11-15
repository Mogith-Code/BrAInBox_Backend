"""Business logic for the community module. Owner: Mogith.

Built so far: the admin side (admin/moderation_admin.py).
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
from api.core.errors import ConflictError, NotFoundError
from api.modules.community import repository
from api.modules.community.schemas import (
    GroupCreate,
    GroupOut,
    ModerationAction,
    ModerationItemOut,
    ModuleStatus,
)
from api.modules.visuals import service as visuals_service
from shared.db.models import CommunityGroup, Notification
from shared.enums import ModerationStatus, NotificationType

MODULE_NAME = "community"
TEXT_PREVIEW_CHARS = 500


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Mogith): student endpoints: groups / posts / replies / votes / reports;
#   auto-tag via ai_client.sync('tag-post'); MODERATE_POST fills moderation_reason / _score.


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
        if action == "remove":
            target.moderation_status = ModerationStatus.REMOVED  # hidden from students
        elif action == "warn" and target.author_id is not None:
            await _warn(session, target.author_id, report.target_type, report.reason, report.id)
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
