"""HTTP endpoints for the performance module. Owner: Keshomigha.

Planned endpoints (details in README.md):
    GET    /api/v1/insights/summary                        Overall progress
    GET    /api/v1/insights/units                          Mastery per unit
    GET    /api/v1/insights/concepts                       Weakest concepts
    GET    /api/v1/mistakes                                My mistakes (filter by type/unit)
    (service) record_mistake() and update_mastery() called by quizzes/exams/evaluation

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.performance import service
from api.modules.performance.schemas import ModuleStatus

router = APIRouter(tags=["Performance"])


@router.get(
    "/performance/status", response_model=ModuleStatus, summary="Placeholder: module status"
)
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Keshomigha): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
