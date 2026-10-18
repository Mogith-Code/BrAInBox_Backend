"""HTTP endpoints for the content module. Owner: Samni.

Planned endpoints (details in README.md):
    GET    /api/v1/topics/{id}/notes                       Approved notes for a topic (full + short)
    POST   /api/v1/uploads                                 Upload a file -> creates SUMMARIZE_UPLOAD job
    GET    /api/v1/uploads/{id}                            Upload status + summary
    GET    /api/v1/library                                 My saved items
    POST   /api/v1/library                                 Save an item
    DELETE /api/v1/library/{id}                            Remove an item

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.content import service
from api.modules.content.schemas import ModuleStatus

router = APIRouter(tags=["Content"])


@router.get("/content/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Samni): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
