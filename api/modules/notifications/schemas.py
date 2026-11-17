"""Request / response models for the notifications module. Owner: Mogith.

They match BrAInBox_Mobile apps/mobile/lib/features/notifications/domain/notifications_models.dart.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from shared.enums import NotificationType

# The app's NotificationKind: picks the icon and the filter chip ("Reminders", "Community"...).
NotificationKind = Literal[
    "reminder", "recommendation", "community", "achievement", "streak", "other"
]


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: NotificationKind
    event: NotificationType  # what happened (job_done, plan_ready, community_reply...)
    title: str
    body: str
    created_at: datetime
    read: bool
    ai_generated: bool
    # Where a tap goes, e.g. {"screen": "post", "post_id": "..."}
    data: dict[str, Any] = Field(default_factory=dict)


class NotificationList(BaseModel):
    """`GET /notifications`: newest first."""

    items: list[NotificationOut]
    unread_count: int


class NotificationUpdate(BaseModel):
    """`PATCH /notifications/{id}`: `{read: true}` (or false to mark it unread again)."""

    read: bool


class ReadAllOut(BaseModel):
    updated: int  # how many were unread
