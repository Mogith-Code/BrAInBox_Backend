"""HTTP endpoints for the evaluation module. Owner: Keshomigha.

Planned endpoints (details in README.md):
    POST   /api/v1/evaluations                             Evaluate a typed answer -> EVALUATE_ANSWER job
    POST   /api/v1/evaluations/ocr                         Upload a handwritten answer photo -> OCR_ANSWER job
    GET    /api/v1/evaluations/{id}                        Result: estimated marks, matched points, feedback

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.evaluation import service
from api.modules.evaluation.schemas import ModuleStatus

router = APIRouter(tags=["Evaluation"])


@router.get("/evaluation/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Keshomigha): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
