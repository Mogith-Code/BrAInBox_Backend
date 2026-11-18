"""HTTP endpoints for the notifications module. Owner: Mogith.

Implemented (used by BrAInBox_Mobile apps/mobile/lib/features/notifications):
    GET    /api/v1/notifications              My notifications, newest first (+ unread_count)
    PATCH  /api/v1/notifications/{id}         {read: true | false}
    POST   /api/v1/notifications/read-all     Mark every notification read

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.notifications import service
from api.modules.notifications.schemas import (
    NotificationList,
    NotificationOut,
    NotificationUpdate,
    ReadAllOut,
)

router = APIRouter(tags=["Notifications"])


@router.get("/notifications", response_model=NotificationList, summary="My notifications")
async def list_notifications(
    user: CurrentUserDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    unread_only: bool = False,
) -> NotificationList:
    """Newest first. `type` is the app's kind (reminder | recommendation | community |
    achievement | streak | other); `event` is what happened (job_done, plan_ready,
    community_reply, system...). `unread_count` counts every unread one (bell badge)."""
    return await service.list_notifications(session, user.id, limit=limit, unread_only=unread_only)


# Declared before /notifications/{notification_id} so "read-all" is never read as an id.
@router.post("/notifications/read-all", response_model=ReadAllOut, summary="Mark all read")
async def mark_all_read(user: CurrentUserDep, session: SessionDep) -> ReadAllOut:
    return await service.mark_all_read(session, user.id)


@router.patch(
    "/notifications/{notification_id}",
    response_model=NotificationOut,
    summary="Mark one notification read (or unread)",
)
async def update_notification(
    notification_id: uuid.UUID, req: NotificationUpdate, user: CurrentUserDep, session: SessionDep
) -> NotificationOut:
    """Errors: 404 `NOTIFICATION_NOT_FOUND` (unknown, or someone else's)."""
    return await service.update_notification(session, user.id, notification_id, req)
