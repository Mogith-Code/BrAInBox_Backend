"""Papers (quizzes, diagnostics, past/model papers), attempts and responses. Owner: Udith."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ContentStatus


class Paper(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "papers"

    title: Mapped[str] = mapped_column(String(200))
    # "quiz" | "diagnostic" | "past_paper" | "model_paper"
    paper_type: Mapped[str] = mapped_column(String(20), default="quiz")
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"), index=True
    )
    year: Mapped[int | None] = mapped_column(Integer)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    total_marks: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.DRAFT
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class PaperQuestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paper_questions"
    __table_args__ = (
        UniqueConstraint("paper_id", "position", name="uq_paper_questions_paper_position"),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)  # 1-based order in the paper
    marks: Mapped[int] = mapped_column(Integer, default=1)


class Attempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A student taking a paper / quiz once."""

    __tablename__ = "attempts"

    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="in_progress")  # |submitted|graded
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[float | None] = mapped_column(Float)
    # Extra result data, e.g. the diagnostic's AI summary:
    # {"summary": "...", "summary_ai_generated": true}
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Response(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The student's answer to one question inside an attempt."""

    __tablename__ = "responses"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attempts.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    selected_option_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mcq_options.id", ondelete="SET NULL"), index=True
    )
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_image_path: Mapped[str | None] = mapped_column(String(500))
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    marks_awarded: Mapped[float | None] = mapped_column(Float)
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer)
