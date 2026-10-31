"""Admin routes: moderation. Owner: Mogith.

Mounted under /api/v1/admin/moderation by `admin/router.py`, which already
requires the admin role for every route in this file.

Implemented:
    GET /admin/moderation/reports                  Visual reports queue (with title + image_url)

Planned endpoints:
    GET /admin/moderation/reports  + posts and replies (community module)
    POST /admin/moderation/reports/{id}/resolve

Admin routes call the services of the owning modules (e.g. `api.modules.content.service`);
they do not have their own SQL.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.admin.schemas import ModuleStatus
from api.modules.visuals import service as visuals_service
from api.modules.visuals.schemas import VisualReportAdminOut
from shared.enums import ModerationStatus

router = APIRouter(prefix="/moderation", tags=["Admin: moderation"])


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    # TODO(Mogith): replace with the endpoints listed above.
    return ModuleStatus(module="moderation_admin", status="todo")


@router.get(
    "/reports",
    response_model=list[VisualReportAdminOut],
    summary="Reports queue (visuals), oldest first",
)
async def list_reports(
    request: Request,
    admin: CurrentUserDep,
    session: SessionDep,
    status: ModerationStatus = ModerationStatus.PENDING,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[VisualReportAdminOut]:
    """Each report has `target_type` "visual", the visual's title and an `image_url` (or its
    `mermaid_code`) so the admin can look at it.

    TODO(Mogith): add community post / reply reports (`content_reports`) to this queue."""
    return await visuals_service.list_reports(session, str(request.base_url), status, limit)
