"""Diagrams / illustrations for topics and student reports about them. Owner: Mogith."""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ContentStatus, ModerationStatus, VisualKind


class Visual(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "visuals"

    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[VisualKind] = mapped_column(str_enum(VisualKind))
    title: Mapped[str] = mapped_column(String(200))
    mermaid_code: Mapped[str | None] = mapped_column(Text)  # for diagram / flowchart
    image_path: Mapped[str | None] = mapped_column(String(500))  # for illustration
    prompt: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.DRAFT
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class VisualReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A student reports a wrong or unclear visual."""

    __tablename__ = "visual_reports"

    visual_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visuals.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(100))
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ModerationStatus] = mapped_column(
        str_enum(ModerationStatus), default=ModerationStatus.PENDING
    )
