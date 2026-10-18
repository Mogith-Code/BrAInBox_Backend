"""Question quality: reviews (AI or human), student reports and usage stats. Owner: Udith."""

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ModerationStatus


class QuestionReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "question_reviews"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    # NULL reviewer_id = reviewed by the AI reviewer
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewer_type: Mapped[str] = mapped_column(String(10), default="ai")  # "ai" | "human"
    verdict: Mapped[str] = mapped_column(String(20))  # "accept" | "revise" | "reject"
    score: Mapped[float | None] = mapped_column(Float)
    comments: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(String(50))


class QuestionReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A student reports a wrong / unclear question."""

    __tablename__ = "question_reports"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(100))
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ModerationStatus] = mapped_column(
        str_enum(ModerationStatus), default=ModerationStatus.PENDING
    )


class QuestionStats(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Running statistics for one question (one row per question)."""

    __tablename__ = "question_stats"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), unique=True, index=True
    )
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_time_seconds: Mapped[float | None] = mapped_column(Float)
    discrimination_index: Mapped[float | None] = mapped_column(Float)
