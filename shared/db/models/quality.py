"""Question quality: reviews (AI or human), student reports and usage stats. Owner: Udith."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ModerationStatus


class QuestionReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One review of a question, by the AI reviewer or an admin. Owner: Udith."""

    __tablename__ = "question_reviews"
    __table_args__ = (
        Index("ix_question_reviews_question_created", "question_id", "created_at"),
        CheckConstraint("reviewer_type IN ('ai', 'admin', 'human')", name="reviewer_type"),
        CheckConstraint("verdict IN ('approve', 'accept', 'revise', 'reject')", name="verdict"),
    )

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    # NULL reviewer_id = reviewed by the AI reviewer
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewer_type: Mapped[str] = mapped_column(String(10), default="ai")  # "ai" | "admin"
    # ReviewDecision value (the spec's `decision`); "accept" is kept for older rows
    verdict: Mapped[str] = mapped_column(String(20))
    # Results of each automatic check, e.g. {"one_correct_answer": true, "in_syllabus": true}
    checks: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    score: Mapped[float | None] = mapped_column(Float)
    comments: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(50))


class QuestionReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A student reports a wrong / unclear question. Owner: Udith."""

    __tablename__ = "question_reports"
    __table_args__ = (
        # The admin queue: reports nobody has handled yet.
        Index("ix_question_reports_open", "status", postgresql_where=text("status = 'pending'")),
    )

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(100))  # QuestionReportReason value
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ModerationStatus] = mapped_column(
        str_enum(ModerationStatus), default=ModerationStatus.PENDING
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuestionStats(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Running statistics for one question (one row per question). Owner: Udith."""

    __tablename__ = "question_stats"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), unique=True, index=True
    )
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)  # the spec's times_answered
    correct_count: Mapped[int] = mapped_column(Integer, default=0)  # the spec's times_correct
    # Filled by Postgres (0.000 - 1.000); never write it yourself.
    correct_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 3),
        Computed(
            "CASE WHEN attempts_count = 0 THEN NULL "
            "ELSE round(correct_count::numeric / attempts_count, 3) END",
            persisted=True,
        ),
    )
    avg_time_seconds: Mapped[float | None] = mapped_column(Float)
    # How many students picked each option, e.g. {"A": 12, "B": 3}
    option_counts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    discrimination_index: Mapped[float | None] = mapped_column(Float)
