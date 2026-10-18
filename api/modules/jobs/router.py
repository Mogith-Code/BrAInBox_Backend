"""HTTP endpoints for the jobs module. Owner: shared.

Planned endpoints (details in README.md):
    GET    /api/v1/jobs/{id}                               Job status + result (only the requester or an admin)

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.jobs import service
from api.modules.jobs.schemas import ModuleStatus

router = APIRouter(tags=["Jobs"])


@router.get("/jobs/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(shared): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
