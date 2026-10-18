"""HTTP endpoints for the questions module. Owner: Udith.

Planned endpoints (details in README.md):
    GET    /api/v1/questions/{id}                          One question with options (no answer key)
    GET    /api/v1/topics/{id}/questions                   Practice questions for a topic
    POST   /api/v1/questions/{id}/explain                  Explain an MCQ answer (sync AI call)

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.questions import service
from api.modules.questions.schemas import ModuleStatus

router = APIRouter(tags=["Questions"])


@router.get("/questions/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Udith): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
