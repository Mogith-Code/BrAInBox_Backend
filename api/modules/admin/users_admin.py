"""Admin routes: users. Owner: Mogith.

Mounted under /api/v1/admin/users by `admin/router.py`, which already
requires the admin role for every route in this file.

Planned endpoints:
    GET /admin/users
    PATCH /admin/users/{id}/role
    POST /admin/users/{id}/disable

Admin routes call the services of the owning modules (e.g. `api.modules.content.service`);
they do not have their own SQL.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.admin.schemas import ModuleStatus

router = APIRouter(prefix="/users", tags=["Admin: users"])


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    # TODO(Mogith): replace with the endpoints listed above.
    return ModuleStatus(module="users_admin", status="todo")
