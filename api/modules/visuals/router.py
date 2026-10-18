"""HTTP endpoints for the visuals module. Owner: Mogith.

Planned endpoints (details in README.md):
    GET    /api/v1/topics/{id}/visuals                     Approved visuals for a topic
    POST   /api/v1/visuals/generate                        Request a visual -> GENERATE_VISUAL job
    POST   /api/v1/visuals/{id}/report                     Report a wrong visual

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.visuals import service
from api.modules.visuals.schemas import ModuleStatus

router = APIRouter(tags=["Visuals"])


@router.get("/visuals/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Mogith): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
