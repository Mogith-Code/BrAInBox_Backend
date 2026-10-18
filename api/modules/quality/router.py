"""HTTP endpoints for the quality module. Owner: Udith.

Planned endpoints (details in README.md):
    POST   /api/v1/questions/{id}/report                   Report a wrong question
    (service) Review-queue logic used by admin/questions_admin.py

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.quality import service
from api.modules.quality.schemas import ModuleStatus

router = APIRouter(tags=["Quality"])


@router.get("/quality/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Udith): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
