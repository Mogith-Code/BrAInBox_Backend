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
    POST   /api/v1/posts/{id}/replies         reply (members of the post's group)
    PATCH  /api/v1/replies/{id}               edit my reply
    DELETE /api/v1/replies/{id}               delete my reply (soft delete; admins too)
    POST   /api/v1/posts/{id}/accept/{reply}  the post's author marks the best answer
    DELETE /api/v1/posts/{id}/accept          the post's author un-marks it
    POST   /api/v1/votes                      +1 / -1 / 0 (remove) on a post or reply
    POST   /api/v1/posts/{id}/report          report a post to the moderators
    POST   /api/v1/replies/{id}/report        report a reply to the moderators

All need a logged-in user.
Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Response, status

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.pagination import Page, PageParamsDep
from api.core.security import CurrentUserDep
from api.modules.community import service
from api.modules.community.repository import PostSort
from api.modules.community.schemas import (
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
    TopicSuggestIn,
    TopicSuggestOut,
    VoteIn,
    VoteOut,
)

router = APIRouter(tags=["Community"])


@router.get("/community/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    return await service.get_status()


# ---------------------------------------------------------------- groups


@router.get("/groups", response_model=list[StudyGroupOut], summary="Study groups I can see")
async def list_groups(user: CurrentUserDep, session: SessionDep) -> list[StudyGroupOut]:
    """ "General" first, then the unit groups. Private groups only when I'm a member."""
    return await service.list_visible_groups(session, user)


@router.get("/groups/{group_id}", response_model=StudyGroupOut, summary="One study group")
async def get_group(group_id: str, user: CurrentUserDep, session: SessionDep) -> StudyGroupOut:
    """`group_id`: the UUID or the slug (`general`, `unit-6`). 404 `GROUP_NOT_FOUND`."""
    return await service.get_group(session, user, group_id)


@router.post("/groups/{group_id}/join", response_model=StudyGroupOut, summary="Join a study group")
async def join_group(group_id: str, user: CurrentUserDep, session: SessionDep) -> StudyGroupOut:
    """Safe to repeat: joining a group I'm already in changes nothing."""
    return await service.join_group(session, user, group_id)


@router.delete(
    "/groups/{group_id}/join", response_model=StudyGroupOut, summary="Leave a study group"
)
async def leave_group(group_id: str, user: CurrentUserDep, session: SessionDep) -> StudyGroupOut:
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
    group_id: str,
    req: PostCreate,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
) -> PostOut:
    """Members only: 403 `NOT_A_MEMBER`. `topic_id` must be in the group's unit: 400
    `TOPIC_NOT_IN_GROUP_UNIT`. The AI classifies the post: `moderation_status` is `flagged`
    (hidden until an admin decides) when it is off-topic or inappropriate. A question also gets
    an AI-suggested answer a few seconds later (a reply with `is_ai_suggested: true`)."""
    return await service.create_post(session, user, group_id, req, ai, background_tasks)


@router.post(
    "/posts/suggest-topic",
    response_model=TopicSuggestOut,
    summary="AI-suggested topic tag for a draft post",
)
async def suggest_topic(
    req: TopicSuggestIn, user: CurrentUserDep, session: SessionDep, ai: AIClientDep
) -> TopicSuggestOut:
    """Call it while the student writes; they can change the suggestion before posting."""
    return await service.suggest_topic(session, user, req, ai)


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


# ---------------------------------------------------------------- replies


@router.post(
    "/posts/{post_id}/replies",
    response_model=ReplyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reply to a post",
)
async def create_reply(
    post_id: uuid.UUID,
    req: ReplyCreate,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
) -> ReplyOut:
    """Members of the post's group only: 403 `NOT_A_MEMBER`. Classified like a post."""
    return await service.create_reply(session, user, post_id, req, ai)


@router.patch("/replies/{reply_id}", response_model=ReplyOut, summary="Edit my reply")
async def update_reply(
    reply_id: uuid.UUID, req: ReplyUpdate, user: CurrentUserDep, session: SessionDep
) -> ReplyOut:
    """Only the author: 403 `NOT_REPLY_AUTHOR`. 404 `REPLY_NOT_FOUND`."""
    return await service.update_reply(session, user, reply_id, req)


@router.delete(
    "/replies/{reply_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete my reply"
)
async def delete_reply(reply_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> Response:
    """The author or an admin. A deleted accepted answer stops being accepted."""
    await service.delete_reply(session, user, reply_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/posts/{post_id}/accept/{reply_id}",
    response_model=PostDetailOut,
    summary="Mark the best answer to my post",
)
async def accept_reply(
    post_id: uuid.UUID, reply_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> PostDetailOut:
    """Only the post's author: 403 `NOT_POST_AUTHOR`. Accepting another reply replaces the old
    one. The reply must belong to this post: 404 `REPLY_NOT_FOUND`."""
    return await service.accept_reply(session, user, post_id, reply_id)


@router.delete(
    "/posts/{post_id}/accept", response_model=PostDetailOut, summary="Un-mark the best answer"
)
async def unaccept_reply(
    post_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> PostDetailOut:
    """Only the post's author: 403 `NOT_POST_AUTHOR`."""
    return await service.accept_reply(session, user, post_id, None)


# ---------------------------------------------------------------- votes + reports


@router.post("/votes", response_model=VoteOut, summary="Vote on a post or reply")
async def vote(req: VoteIn, user: CurrentUserDep, session: SessionDep) -> VoteOut:
    """Send `post_id` OR `reply_id`, and `value` 1 / -1 (0 removes my vote). Voting again
    changes my vote. Members only (403 `NOT_A_MEMBER`); not on my own (403 `CANNOT_VOTE_OWN`)."""
    return await service.vote(session, user, req)


@router.post(
    "/posts/{post_id}/report",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Report a post to the moderators",
)
async def report_post(
    post_id: uuid.UUID, req: ReportIn, user: CurrentUserDep, session: SessionDep
) -> ReportOut:
    """409 `ALREADY_REPORTED` while my last report is open; 400 `CANNOT_REPORT_OWN`."""
    return await service.report(session, user, req, post_id=post_id)


@router.post(
    "/replies/{reply_id}/report",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Report a reply to the moderators",
)
async def report_reply(
    reply_id: uuid.UUID, req: ReportIn, user: CurrentUserDep, session: SessionDep
) -> ReportOut:
    """409 `ALREADY_REPORTED` while my last report is open; 400 `CANNOT_REPORT_OWN`."""
    return await service.report(session, user, req, reply_id=reply_id)
