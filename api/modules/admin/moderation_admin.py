"""Admin routes: moderation. Owner: Mogith.

Mounted under /api/v1/admin/moderation by `admin/router.py`, which already
requires the admin role for every route in this file.

Planned endpoints:
    GET /admin/moderation/reports (posts, replies, visuals)
    POST /admin/moderation/reports/{id}/resolve

Admin routes call the services of the owning modules (e.g. `api.modules.content.service`);
they do not have their own SQL.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.admin.schemas import ModuleStatus

router = APIRouter(prefix="/moderation", tags=["Admin: moderation"])


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    # TODO(Mogith): replace with the endpoints listed above.
    return ModuleStatus(module="moderation_admin", status="todo")
