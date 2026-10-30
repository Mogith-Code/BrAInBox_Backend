"""Papers (quizzes, diagnostics, past/model papers), attempts and responses. Owner: Udith."""

import uuid
from datetime import datetime
from typing import Any

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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import AIGeneratedMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import AttemptKind, AttemptMode, ContentStatus


class Paper(UUIDPrimaryKeyMixin, TimestampMixin, AIGeneratedMixin, Base):
    """A set of questions: quiz, diagnostic, past paper, model paper. Owner: Udith."""

    __tablename__ = "papers"
    __table_args__ = (
        CheckConstraint(
            "paper_type IN ('quiz', 'model_paper', 'past_paper', 'diagnostic', 'ai_generated')",
            name="paper_type",
        ),
    )

    title: Mapped[str] = mapped_column(String(200))
    # PaperKind value: quiz | diagnostic | past_paper | model_paper | ai_generated
    paper_type: Mapped[str] = mapped_column(String(20), default="quiz")
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"), index=True
    )
    # Units this paper covers, and how it was built, e.g. {"mcq": 50, "units": {...}}
    unit_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, server_default="{}"
    )
    blueprint: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    year: Mapped[int | None] = mapped_column(Integer)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)  # the spec's time_limit_minutes
    total_marks: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.DRAFT
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class PaperQuestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One question at one position inside a paper. Owner: Udith."""

    __tablename__ = "paper_questions"
    __table_args__ = (
        UniqueConstraint("paper_id", "position", name="uq_paper_questions_paper_position"),
        UniqueConstraint("paper_id", "question_id", name="uq_paper_questions_paper_question"),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)  # 1-based order (the spec's order_index)
    marks: Mapped[int] = mapped_column(Integer, default=1)


class Attempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A student taking a paper / quiz / the diagnostic once. Owner: Udith."""

    __tablename__ = "attempts"
    __table_args__ = (
        Index("ix_attempts_user_kind_status", "user_id", "kind", "status"),
        # Only one unfinished diagnostic per student.
        Index(
            "uq_attempts_one_open_diagnostic",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'diagnostic' AND status = 'in_progress'"),
        ),
        CheckConstraint(
            "status IN ('in_progress', 'submitted', 'evaluated', 'abandoned', 'graded')",
            name="status",
        ),
    )

    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[AttemptKind] = mapped_column(
        str_enum(AttemptKind), default=AttemptKind.QUIZ, server_default="quiz"
    )
    mode: Mapped[AttemptMode] = mapped_column(
        str_enum(AttemptMode), default=AttemptMode.PRACTICE, server_default="practice"
    )
    # AttemptStatus value: in_progress -> submitted -> graded / evaluated (or abandoned)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    # For topic / unit quizzes
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    # Frozen question order, so "resume" shows the same questions
    question_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, server_default="{}"
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    max_score: Mapped[float | None] = mapped_column(Float)
    percentage: Mapped[float | None] = mapped_column(Float)
    # Extra result data, e.g. the diagnostic's AI summary:
    # {"summary": "...", "summary_ai_generated": true}
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Response(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The student's answer to one question inside an attempt. Owner: Udith.

    Photos of handwritten answers: answers/{user_id}/{response_id}/page-{n}.jpg
    """

    __tablename__ = "responses"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", name="uq_responses_attempt_question"),
    )

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
    answer_image_path: Mapped[str | None] = mapped_column(String(500))  # first page (older code)
    image_paths: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    ocr_text: Mapped[str | None] = mapped_column(Text)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    marks_awarded: Mapped[float | None] = mapped_column(Float)
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
