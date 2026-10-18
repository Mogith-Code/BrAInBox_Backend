"""Admin routes: content. Owner: Samni.

Mounted under /api/v1/admin/content by `admin/router.py`, which already
requires the admin role for every route in this file.

Planned endpoints:
    GET/POST/PATCH /admin/content/notes
    POST /admin/content/notes/{id}/approve
    POST /admin/content/notes/generate (GENERATE_NOTES job)

Admin routes call the services of the owning modules (e.g. `api.modules.content.service`);
they do not have their own SQL.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.admin.schemas import ModuleStatus

router = APIRouter(prefix="/content", tags=["Admin: content"])


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    # TODO(Samni): replace with the endpoints listed above.
    return ModuleStatus(module="content_admin", status="todo")
