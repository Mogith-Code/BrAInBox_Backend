"""Notes, student uploads, summaries and the personal library. Owner: Samni."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ContentStatus, JobStatus


class Note(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Topic notes (full or short), AI-generated or written by an admin."""

    __tablename__ = "notes"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    note_type: Mapped[str] = mapped_column(String(20), default="full")  # "full" | "short"
    body_md: Mapped[str] = mapped_column(Text)
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.DRAFT
    )
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    # RAG citations used to generate this note, for admin review:
    # [{"chunk_id": "...", "document_title": "...", "page": 3}, ...]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class Upload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A file a student uploaded (PDF, image...) to be summarised."""

    __tablename__ = "uploads"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))  # path in Firebase Storage
    mime_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    processing_status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus), default=JobStatus.QUEUED
    )


class Summary(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """AI summary of an upload (or of a topic)."""

    __tablename__ = "summaries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    upload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("uploads.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    body_md: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(50))


class LibraryItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Something a student saved to their library (note, summary, visual...)."""

    __tablename__ = "library_items"
    __table_args__ = (
        UniqueConstraint("user_id", "item_type", "item_id", name="uq_library_items_user_type_item"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    item_type: Mapped[str] = mapped_column(String(30))  # "note" | "summary" | "visual" | ...
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200))
