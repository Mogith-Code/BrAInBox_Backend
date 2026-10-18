"""HTTP endpoints for the syllabus module. Owner: Keshomigha.

Planned endpoints (details in README.md):
    GET    /api/v1/units                                   All 10 units
    GET    /api/v1/units/{id}/topics                       Topics of a unit
    GET    /api/v1/topics/{id}                             One topic with its concepts

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.syllabus import service
from api.modules.syllabus.schemas import ModuleStatus

router = APIRouter(tags=["Syllabus"])


@router.get("/syllabus/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Keshomigha): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
