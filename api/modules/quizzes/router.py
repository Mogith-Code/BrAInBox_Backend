"""HTTP endpoints for the quizzes module. Owner: Udith.

Planned endpoints (details in README.md):
    POST   /api/v1/quizzes                                 Start a quiz for a topic/unit
    GET    /api/v1/quizzes/{id}                            Quiz with questions
    POST   /api/v1/quizzes/{id}/responses                  Submit answers
    GET    /api/v1/quizzes/{id}/results                    Score + explanations
    POST   /api/v1/quizzes/diagnostic                      Start the diagnostic test

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.quizzes import service
from api.modules.quizzes.schemas import ModuleStatus

router = APIRouter(tags=["Quizzes"])


@router.get("/quizzes/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Udith): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
