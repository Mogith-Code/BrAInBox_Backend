"""HTTP endpoints for the community module. Owner: Mogith.

    GET    /api/v1/groups                     groups I can see (General first, then units)
    GET    /api/v1/groups/{id}                one group (UUID or slug, e.g. "unit-6")
    POST   /api/v1/groups/{id}/join           join (joining again changes nothing)
    DELETE /api/v1/groups/{id}/join           leave (leaving again changes nothing)

Planned endpoints (details in README.md):
    GET    /api/v1/groups/{id}/posts          Feed of a group
    POST   /api/v1/groups/{id}/posts          Create a post (published straight away for now)
    GET    /api/v1/posts/{id}                 Post with replies
    POST   /api/v1/posts/{id}/replies         Reply
    POST   /api/v1/votes                      Up/down vote a post or reply
    POST   /api/v1/posts/{id}/report          Report a post (and replies) to moderators

All need a logged-in user.
Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.community import service
from api.modules.community.schemas import GroupOut, ModuleStatus

router = APIRouter(tags=["Community"])


@router.get("/community/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    return await service.get_status()


# ---------------------------------------------------------------- groups


@router.get("/groups", response_model=list[GroupOut], summary="Study groups I can see")
async def list_groups(user: CurrentUserDep, session: SessionDep) -> list[GroupOut]:
    """ "General" first, then the unit groups. Private groups only when I'm a member."""
    return await service.list_groups(session, user)


@router.get("/groups/{group_id}", response_model=GroupOut, summary="One study group")
async def get_group(group_id: str, user: CurrentUserDep, session: SessionDep) -> GroupOut:
    """`group_id`: the UUID or the slug (`general`, `unit-6`). 404 `GROUP_NOT_FOUND`."""
    return await service.get_group(session, user, group_id)


@router.post("/groups/{group_id}/join", response_model=GroupOut, summary="Join a study group")
async def join_group(group_id: str, user: CurrentUserDep, session: SessionDep) -> GroupOut:
    """Safe to repeat: joining a group I'm already in changes nothing."""
    return await service.join_group(session, user, group_id)


@router.delete("/groups/{group_id}/join", response_model=GroupOut, summary="Leave a study group")
async def leave_group(group_id: str, user: CurrentUserDep, session: SessionDep) -> GroupOut:
    """Safe to repeat: leaving a group I'm not in changes nothing."""
    return await service.leave_group(session, user, group_id)
