"""HTTP endpoints for the recommendations module. Owner: Udith.

Planned endpoints (details in README.md):
    GET    /api/v1/recommendations                         My recommendations
    POST   /api/v1/recommendations/{id}/dismiss            Hide one
    GET    /api/v1/study-plan                              My active study plan
    POST   /api/v1/study-plan                              Create / regenerate a plan
    PATCH  /api/v1/study-plan/items/{id}                   Mark an item done

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.recommendations import service
from api.modules.recommendations.schemas import ModuleStatus

router = APIRouter(tags=["Recommendations"])


@router.get(
    "/recommendations/status", response_model=ModuleStatus, summary="Placeholder: module status"
)
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Udith): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
