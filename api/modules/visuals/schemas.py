"""Request / response models (Pydantic) for the visuals module. Owner: Mogith.

JSON is snake_case and matches the Flutter app
(BrainBox_front: packages/brainbox_core/lib/models/visual.dart and
apps/mobile/lib/features/visuals/domain/visuals_models.dart).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from shared.enums import (
    ModerationStatus,
    VisualKind,
    VisualReportReason,
    VisualStyle,
    VisualType,
)

MIN_PROMPT_CHARS = 5
MAX_PROMPT_CHARS = 300
MAX_DETAILS_CHARS = 500


class VisualLabelOut(BaseModel):
    """One numbered label. x / y are 0-1 fractions of the image (null = list it only)."""

    number: int
    name: str
    description: str = ""
    x: float | None = None
    y: float | None = None


class VisualOut(BaseModel):
    id: uuid.UUID
    title: str
    topic_id: uuid.UUID | None = None
    concept_id: uuid.UUID | None = None
    kind: VisualKind
    image_url: str | None = None  # PNG the phone can load without a login header
    mermaid_code: str | None = None  # the app renders this itself when image_url is null
    alt_text: str | None = None
    labels: list[VisualLabelOut] = Field(default_factory=list)
    style: VisualStyle | None = None
    width: int | None = None  # PNG size in pixels
    height: int | None = None
    is_ai_generated: bool
    is_verified: bool  # an admin checked it
    created_at: datetime


class TopicVisualsOut(BaseModel):
    """`GET /topics/{topic_id}/visuals`: the topic header + its visuals, newest first."""

    topic_id: uuid.UUID
    topic_title: str
    unit_code: str | None = None  # "6" = Unit 6 (same as the home and quizzes modules)
    unit_title: str | None = None
    visuals: list[VisualOut]


class GenerateVisualIn(BaseModel):
    prompt: str = Field(min_length=MIN_PROMPT_CHARS, max_length=MAX_PROMPT_CHARS)
    visual_type: VisualType
    style: VisualStyle
    topic_id: uuid.UUID | None = None

    @field_validator("prompt")
    @classmethod
    def strip_prompt(cls, value: str) -> str:
        """Spaces do not count: "     " is too short."""
        value = value.strip()
        if len(value) < MIN_PROMPT_CHARS:
            raise ValueError(f"Prompt must have at least {MIN_PROMPT_CHARS} characters")
        return value


class JobCreatedOut(BaseModel):
    job_id: uuid.UUID


class ReportVisualIn(BaseModel):
    reason: VisualReportReason
    details: str | None = Field(default=None, max_length=MAX_DETAILS_CHARS)


class VisualReportOut(BaseModel):
    id: uuid.UUID
    visual_id: uuid.UUID
    reason: VisualReportReason
    details: str | None = None
    status: ModerationStatus
    created_at: datetime


class VisualReportAdminOut(VisualReportOut):
    """One row of the admin reports queue (admin/moderation_admin.py)."""

    target_type: str = "visual"
    reported_by: uuid.UUID
    visual_title: str
    image_url: str | None = None
    mermaid_code: str | None = None
