"""Admin routes: students. Owner: Mogith.

Mounted under /api/v1/admin/users by `admin/router.py`, which already
requires the admin role for every route in this file.

    GET   /admin/users          students, filtered + paged, with status and average mastery
    PATCH /admin/users/{id}     {is_active}: suspend (false) or reinstate (true)

Admin routes call the services of the owning modules (here `api.modules.auth.service`);
they do not have their own SQL.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.admin import service as admin_service
from api.modules.admin.schemas import ModuleStatus
from api.modules.auth import service as auth_service
from api.modules.auth.schemas import AdminStudentOut, AdminStudentPage, AdminStudentUpdate

router = APIRouter(prefix="/users", tags=["Admin: users"])


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    return ModuleStatus(module="users_admin", status="todo")


@router.get("", response_model=AdminStudentPage, summary="Students, filtered and paged")
async def list_students(
    admin: CurrentUserDep,
    session: SessionDep,
    search: Annotated[str | None, Query(max_length=100, description="Name or email")] = None,
    exam_year: int | None = None,
    status: Literal["active", "suspended", "inactive"] | None = None,
    district: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminStudentPage:
    """`search` matches the name or email (any case). `status`: **suspended** = account
    disabled; **inactive** = no study activity for 30+ days; **active** = the rest.
    `total` counts the matching students, `active_total` the active ones among them
    (ignoring `status`). `avg_mastery` (0-100) is null when the student has no data yet."""
    return await auth_service.admin_list_students(
        session,
        search=search,
        exam_year=exam_year,
        status=status,
        district=district,
        offset=(page - 1) * page_size,
        limit=page_size,
    )


@router.patch("/{user_id}", response_model=AdminStudentOut, summary="Suspend or reinstate")
async def set_active(
    user_id: uuid.UUID, req: AdminStudentUpdate, admin: CurrentUserDep, session: SessionDep
) -> AdminStudentOut:
    """Suspending disables the Firebase account too (the student then gets `USER_DISABLED`).

    Errors: 400 `CANNOT_SUSPEND_SELF` · 404 `USER_NOT_FOUND` · 422 · 503 `FIREBASE_ERROR`."""
    row = await auth_service.admin_set_active(session, admin.id, user_id, req.is_active)
    action = "user.reinstate" if req.is_active else "user.suspend"
    await admin_service.record_audit(session, admin, action, "user", user_id)
    return row
