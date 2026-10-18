"""HTTP endpoints for the community module. Owner: Mogith.

Planned endpoints (details in README.md):
    GET    /api/v1/groups                                  List groups
    POST   /api/v1/groups                                  Create a group
    POST   /api/v1/groups/{id}/join                        Join a group
    GET    /api/v1/posts                                   Feed (filter by group/topic/tag)
    POST   /api/v1/posts                                   Create a post -> MODERATE_POST + SUGGEST_ANSWER jobs
    GET    /api/v1/posts/{id}                              Post with replies
    POST   /api/v1/posts/{id}/replies                      Reply
    POST   /api/v1/votes                                   Up/down vote a post or reply
    POST   /api/v1/reports                                 Report a post or reply

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.community import service
from api.modules.community.schemas import ModuleStatus

router = APIRouter(tags=["Community"])


@router.get("/community/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Mogith): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
