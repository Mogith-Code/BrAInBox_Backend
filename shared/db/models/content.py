"""Notes, student uploads, summaries and the personal library. Owner: Samni."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import AIGeneratedMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ContentSource, ContentStatus, JobStatus, UploadStatus

# Max upload size: 20 MB
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class Note(UUIDPrimaryKeyMixin, TimestampMixin, AIGeneratedMixin, Base):
    """Topic notes (full or short), AI-generated or written by an admin. Owner: Samni."""

    __tablename__ = "notes"
    __table_args__ = (
        # One approved topic-level note per topic and kind, cached for every student.
        Index(
            "uq_notes_topic_kind_approved",
            "topic_id",
            "note_type",
            unique=True,
            postgresql_where=text("status = 'approved' AND concept_id IS NULL"),
        ),
        CheckConstraint("note_type IN ('full', 'short')", name="note_type"),
    )

    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="RESTRICT"), index=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    note_type: Mapped[str] = mapped_column(String(20), default="full")  # NoteKind: full | short
    body_md: Mapped[str] = mapped_column(Text)
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.DRAFT, index=True
    )
    source: Mapped[ContentSource] = mapped_column(
        str_enum(ContentSource), default=ContentSource.AI, server_default="ai"
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # RAG citations used to generate this note, for admin review (the spec's `sources`):
    # [{"chunk_id": "...", "document_title": "...", "page": 3}, ...]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)


class Upload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A file a student uploaded (PDF, image...) to be summarised. Owner: Samni.

    Stored in Firebase Storage, e.g. uploads/{user_id}/{upload_id}.pdf (docs/database.md)
    """

    __tablename__ = "uploads"
    __table_args__ = (
        Index("ix_uploads_user_created", "user_id", "created_at"),
        CheckConstraint(
            f"size_bytes > 0 AND size_bytes <= {MAX_UPLOAD_BYTES}", name="size_bytes_range"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(255))
    file_name: Mapped[str] = mapped_column(String(255))  # the spec's `original_filename`
    file_path: Mapped[str] = mapped_column(String(500))  # path in Firebase Storage
    mime_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus), default=JobStatus.QUEUED
    )
    error: Mapped[str | None] = mapped_column(Text)


class Summary(UUIDPrimaryKeyMixin, TimestampMixin, AIGeneratedMixin, Base):
    """AI summary of an upload (or of a topic). Owner: Samni."""

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
    body_md: Mapped[str] = mapped_column(Text)  # the spec's `summary_md`
    key_points: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    key_terms: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    status: Mapped[UploadStatus] = mapped_column(
        str_enum(UploadStatus), default=UploadStatus.READY, server_default="ready"
    )
    error: Mapped[str | None] = mapped_column(Text)


class LibraryItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Something a student saved to their library (note, summary, visual...). Owner: Samni.

    `item_id` is polymorphic: it points to notes / summaries / visuals / questions /
    resources / posts depending on `item_type`, so it has NO foreign key. Code must check
    that the item exists, and handle items that were deleted later.
    """

    __tablename__ = "library_items"
    __table_args__ = (
        UniqueConstraint("user_id", "item_type", "item_id", name="uq_library_items_user_type_item"),
        CheckConstraint(
            "item_type IN ('note', 'summary', 'visual', 'question', 'resource', 'post')",
            name="item_type",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    item_type: Mapped[str] = mapped_column(String(30))  # LibraryItemType value
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200))
    folder: Mapped[str | None] = mapped_column(String(80))
