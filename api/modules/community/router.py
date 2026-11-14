"""HTTP endpoints for the community module. Owner: Mogith.

    GET    /api/v1/groups                     groups I can see (General first, then units)
    GET    /api/v1/groups/{id}                one group (UUID or slug, e.g. "unit-6")
    POST   /api/v1/groups/{id}/join           join (joining again changes nothing)
    DELETE /api/v1/groups/{id}/join           leave (leaving again changes nothing)
    GET    /api/v1/groups/{id}/posts          feed of a group (?sort=new|top, paged)
    POST   /api/v1/groups/{id}/posts          create a post (members; published straight away)
    GET    /api/v1/posts/{id}                 a post with its replies
    PATCH  /api/v1/posts/{id}                 edit my post
    DELETE /api/v1/posts/{id}                 delete my post (soft delete; admins too)

Planned endpoints (details in README.md):
    POST   /api/v1/posts/{id}/replies         Reply
    POST   /api/v1/votes                      Up/down vote a post or reply
    POST   /api/v1/posts/{id}/report          Report a post (and replies) to moderators

All need a logged-in user.
Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter, Response, status

from api.core.database import SessionDep
from api.core.pagination import Page, PageParamsDep
from api.core.security import CurrentUserDep
from api.modules.community import service
from api.modules.community.repository import PostSort
from api.modules.community.schemas import (
    GroupOut,
    ModuleStatus,
    PostCreate,
    PostDetailOut,
    PostOut,
    PostUpdate,
)

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


# ---------------------------------------------------------------- posts


@router.get("/groups/{group_id}/posts", response_model=Page[PostOut], summary="A group's posts")
async def list_posts(
    group_id: str,
    user: CurrentUserDep,
    session: SessionDep,
    paging: PageParamsDep,
    sort: PostSort = "new",
) -> Page[PostOut]:
    """`sort=new` (newest first) or `top` (highest score first). Paged with `page` / `size`.
    I see approved posts, plus my own posts that are still pending or flagged."""
    return await service.list_posts(session, user, group_id, sort, paging)


@router.post(
    "/groups/{group_id}/posts",
    response_model=PostOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a post in a group",
)
async def create_post(
    group_id: str, req: PostCreate, user: CurrentUserDep, session: SessionDep
) -> PostOut:
    """Members only: 403 `NOT_A_MEMBER`. `topic_id` must be in the group's unit: 400
    `TOPIC_NOT_IN_GROUP_UNIT`. Published straight away for now."""
    return await service.create_post(session, user, group_id, req)


@router.get("/posts/{post_id}", response_model=PostDetailOut, summary="A post with its replies")
async def get_post(post_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> PostDetailOut:
    """Replies: the accepted answer first, then the highest score. 404 `POST_NOT_FOUND`."""
    return await service.get_post(session, user, post_id)


@router.patch("/posts/{post_id}", response_model=PostOut, summary="Edit my post")
async def update_post(
    post_id: uuid.UUID, req: PostUpdate, user: CurrentUserDep, session: SessionDep
) -> PostOut:
    """Send only the fields to change. Only the author: 403 `NOT_POST_AUTHOR`."""
    return await service.update_post(session, user, post_id, req)


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete my post")
async def delete_post(post_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> Response:
    """The author or an admin. Soft delete: replies and votes stay, but nobody sees the post."""
    await service.delete_post(session, user, post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
