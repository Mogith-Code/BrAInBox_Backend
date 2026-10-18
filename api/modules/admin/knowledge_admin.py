"""Admin routes: knowledge. Owner: Keshomigha.

Mounted under /api/v1/admin/knowledge by `admin/router.py`, which already
requires the admin role for every route in this file.

Planned endpoints:
    GET/POST/PATCH /admin/knowledge/model-answers
    POST /admin/knowledge/model-answers/{id}/points
    POST /admin/knowledge/points/{id}/keywords

Admin routes call the services of the owning modules (e.g. `api.modules.content.service`);
they do not have their own SQL.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.admin.schemas import ModuleStatus

router = APIRouter(prefix="/knowledge", tags=["Admin: knowledge base"])


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    # TODO(Keshomigha): replace with the endpoints listed above.
    return ModuleStatus(module="knowledge_admin", status="todo")
