"""Admin routes: analytics. Owner: Keshomigha.

Mounted under /api/v1/admin/analytics by `admin/router.py`, which already
requires the admin role for every route in this file.

Planned endpoints:
    GET /admin/analytics/overview
    GET /admin/analytics/performance
    GET /admin/analytics/ai-usage (ai_usage_log, cost)

Admin routes call the services of the owning modules (e.g. `api.modules.content.service`);
they do not have their own SQL.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.admin.schemas import ModuleStatus

router = APIRouter(prefix="/analytics", tags=["Admin: analytics"])


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    # TODO(Keshomigha): replace with the endpoints listed above.
    return ModuleStatus(module="analytics_admin", status="todo")
