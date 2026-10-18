"""HTTP endpoints for the knowledge_base module. Owner: Keshomigha.

Planned endpoints (details in README.md):
    GET    /api/v1/knowledge-base/questions/{id}/model-answer Model answer (after an attempt)
    (service) get_marking_scheme(question_id) used by evaluation

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.knowledge_base import service
from api.modules.knowledge_base.schemas import ModuleStatus

router = APIRouter(tags=["Knowledge base"])


@router.get(
    "/knowledge-base/status", response_model=ModuleStatus, summary="Placeholder: module status"
)
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Keshomigha): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
