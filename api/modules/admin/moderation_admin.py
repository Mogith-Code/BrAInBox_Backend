"""Admin routes: moderation + study groups. Owner: Mogith.

Mounted under /api/v1/admin by `admin/router.py`, which already requires the admin role for
every route in this file. (No prefix here, because study groups live under /admin/community.)

    GET  /admin/moderation/reports                  open reports, one per target, oldest first
    POST /admin/moderation/reports/{id}/resolve     {action: keep | warn | remove} -> 204
    GET  /admin/community/groups                    study groups
    POST /admin/community/groups                    {name} -> the new group

Admin routes call the services of the owning modules (here `api.modules.community.service`);
they do not have their own SQL.
"""

import uuid

from fastapi import APIRouter, Request, Response, status

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.admin import service as admin_service
from api.modules.admin.schemas import ModuleStatus
from api.modules.community import service as community_service
from api.modules.community.schemas import GroupCreate, GroupOut, ModerationItemOut, ResolveReportIn

router = APIRouter(tags=["Admin: moderation"])


@router.get(
    "/moderation/status", response_model=ModuleStatus, summary="Placeholder: admin area status"
)
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    return ModuleStatus(module="moderation_admin", status="todo")


@router.get(
    "/moderation/reports",
    response_model=list[ModerationItemOut],
    summary="Open reports (posts, replies, visuals), one per target, oldest first",
)
async def list_reports(
    request: Request, admin: CurrentUserDep, session: SessionDep
) -> list[ModerationItemOut]:
    """`id` is the oldest open report of the target; `report_count` how many are open.
    Visuals have `visual_title` + `image_url`; posts / replies have `text`, `group_name` and
    the AI moderator's `ai_flag_label` / `ai_flag_score` (0-1) when it flagged them."""
    return await community_service.moderation_queue(session, str(request.base_url))


@router.post(
    "/moderation/reports/{report_id}/resolve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Keep, warn or remove a reported post / reply / visual",
)
async def resolve_report(
    report_id: uuid.UUID, req: ResolveReportIn, admin: CurrentUserDep, session: SessionDep
) -> Response:
    """Closes every open report of the same target.
    **keep** = dismiss · **warn** = notify the author + dismiss · **remove** = hide it.

    Errors: 404 `REPORT_NOT_FOUND` · 409 `REPORT_ALREADY_RESOLVED` · 422."""
    target = await community_service.resolve_report(session, admin.id, report_id, req.action)
    await admin_service.record_audit(
        session, admin, f"report.{req.action}", "report", report_id, {"target_type": target}
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/community/groups", response_model=list[GroupOut], summary="Study groups")
async def list_groups(admin: CurrentUserDep, session: SessionDep) -> list[GroupOut]:
    """`moderator_name` is null when the group has no moderator. `is_open` = anyone can join."""
    return await community_service.list_groups(session)


@router.post(
    "/community/groups",
    response_model=GroupOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a study group",
)
async def create_group(req: GroupCreate, admin: CurrentUserDep, session: SessionDep) -> GroupOut:
    """Errors: 409 `GROUP_NAME_TAKEN` · 422 (name not 2-120 characters)."""
    group = await community_service.create_group(session, admin.id, req)
    await admin_service.record_audit(session, admin, "group.create", "group", group.id)
    return group
