"""Request / response models (Pydantic) for the community module. Owner: Mogith.

The admin models match the Flutter admin app
(BrAInBox_Mobile apps/admin/lib/features/moderation/domain/moderation_models.dart).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- admin: moderation queue
ReportTargetType = Literal["post", "reply", "visual"]
ModerationAction = Literal["keep", "warn", "remove"]


class ModerationItemOut(BaseModel):
    """One reported post / reply / visual. All open reports of the same target are one item;
    `id` is the oldest open report (use it to resolve them all)."""

    id: uuid.UUID
    target_type: ReportTargetType
    target_id: uuid.UUID
    reason: str
    details: str | None = None
    author_handle: str | None = None
    group_name: str | None = None
    text: str | None = None  # post / reply text (or the visual's prompt)
    visual_title: str | None = None
    image_url: str | None = None
    ai_flag_label: str | None = None
    ai_flag_score: float | None = None  # 0-1
    report_count: int = 1
    created_at: datetime


class ResolveReportIn(BaseModel):
    action: ModerationAction


# ---------------------------------------------------------------- admin: study groups
class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    members: int
    moderator_name: str | None = None  # null = no moderator yet
    is_open: bool


class GroupCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Name must have at least 2 characters")
        return value
