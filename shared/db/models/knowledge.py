"""Marking knowledge base: model answers -> answer points -> keywords. Owner: Keshomigha."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import EMBEDDING_DIM, Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ContentStatus


class ModelAnswer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The model (ideal) answer of a structured / essay question. Owner: Keshomigha."""

    __tablename__ = "model_answers"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    answer_text: Mapped[str] = mapped_column(Text)  # markdown (the spec's `answer_md`)
    total_marks: Mapped[float] = mapped_column(Float, default=0)
    # ModelAnswerSource value (marking_scheme | admin | ai) or a free note like
    # "marking scheme 2023" from older rows
    source: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.DRAFT
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnswerPoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One marking point of a model answer (e.g. "mentions ATP is used" = 1 mark)."""

    __tablename__ = "answer_points"
    __table_args__ = (
        Index(
            "ix_answer_points_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        CheckConstraint("marks > 0", name="marks_positive"),
    )

    model_answer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_answers.id", ondelete="CASCADE"), index=True
    )
    point_text: Mapped[str] = mapped_column(Text)
    marks: Mapped[float] = mapped_column(Float, default=1)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Used for semantic (meaning-based) marking
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(64))


class Keyword(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A keyword (with synonyms) that shows an answer point was made. Owner: Keshomigha."""

    __tablename__ = "keywords"
    __table_args__ = (
        # The same keyword only once per answer point, ignoring case.
        Index(
            "uq_keywords_point_keyword_lower",
            "answer_point_id",
            text("lower(keyword)"),
            unique=True,
        ),
    )

    answer_point_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("answer_points.id", ondelete="CASCADE"), index=True
    )
    keyword: Mapped[str] = mapped_column(String(100))
    synonyms: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), default=list, server_default="{}"
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0)
