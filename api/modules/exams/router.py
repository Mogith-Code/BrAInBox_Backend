"""HTTP endpoints for the exams module. Owner: Udith.

Planned endpoints (details in README.md):
    GET    /api/v1/papers                                  List papers
    GET    /api/v1/papers/{id}                             One paper
    POST   /api/v1/papers/generate                         Build a model paper -> BUILD_PAPER job
    POST   /api/v1/attempts                                Start an attempt
    GET    /api/v1/attempts/{id}                           Attempt with answers
    POST   /api/v1/attempts/{id}/submit                    Submit an attempt

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.exams import service
from api.modules.exams.schemas import ModuleStatus

router = APIRouter(tags=["Exams"])


@router.get("/exams/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Udith): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
