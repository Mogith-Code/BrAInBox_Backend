"""Diagrams / illustrations for topics and student reports about them. Owner: Mogith.

Illustrations are stored in Firebase Storage at visuals/{concept_id}/{visual_id}.png
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import AIGeneratedMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ContentStatus, ModerationStatus, VisualKind


class Visual(UUIDPrimaryKeyMixin, TimestampMixin, AIGeneratedMixin, Base):
    """A Mermaid diagram or an AI illustration for a topic / concept. Owner: Mogith."""

    __tablename__ = "visuals"
    __table_args__ = (Index("ix_visuals_concept_status", "concept_id", "status"),)

    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="RESTRICT"), index=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[VisualKind] = mapped_column(str_enum(VisualKind))
    title: Mapped[str] = mapped_column(String(200))
    mermaid_code: Mapped[str | None] = mapped_column(Text)  # for diagram / flowchart
    image_path: Mapped[str | None] = mapped_column(String(500))  # for illustration
    alt_text: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    prompt: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.DRAFT
    )
    safety_passed: Mapped[bool | None] = mapped_column(Boolean)
    # Who asked for it (the spec's `requested_by`).
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VisualReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A student reports a wrong or unclear visual. Owner: Mogith."""

    __tablename__ = "visual_reports"

    visual_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visuals.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(100))  # VisualReportReason value
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ModerationStatus] = mapped_column(
        str_enum(ModerationStatus), default=ModerationStatus.PENDING
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
