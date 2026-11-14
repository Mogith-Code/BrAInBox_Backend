"""Business logic for the community module. Owner: Mogith.

Groups: every student sees the public groups ("General" first, then one per unit) and can join
or leave them. A private group is only visible to its members and can't be joined from the app.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.errors import NotFoundError
from api.core.security import CurrentUser
from api.modules.community import repository
from api.modules.community.repository import GroupRef
from api.modules.community.schemas import GroupOut, ModuleStatus
from shared.db.models import CommunityGroup

MODULE_NAME = "community"


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
