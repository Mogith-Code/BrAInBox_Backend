"""Evaluations of written (structured / essay) answers. Owner: Keshomigha."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import AIGeneratedMixin, Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import EvaluationMethod, JobStatus


class Evaluation(UUIDPrimaryKeyMixin, TimestampMixin, AIGeneratedMixin, Base):
    """The AI's marking of one written answer. Owner: Keshomigha."""

    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint(
            "estimated_marks >= 0 AND estimated_marks <= max_marks", name="marks_range"
        ),
        CheckConstraint("keyword_coverage BETWEEN 0 AND 1", name="keyword_coverage_range"),
        CheckConstraint("semantic_score BETWEEN 0 AND 1", name="semantic_score_range"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    response_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("responses.id", ondelete="SET NULL"), index=True
    )
    answer_text: Mapped[str | None] = mapped_column(Text)  # typed answer
    answer_image_path: Mapped[str | None] = mapped_column(String(500))  # handwritten photo
    ocr_text: Mapped[str | None] = mapped_column(Text)  # text read from the photo
    method: Mapped[EvaluationMethod | None] = mapped_column(str_enum(EvaluationMethod))
    estimated_marks: Mapped[float | None] = mapped_column(Float)
    max_marks: Mapped[float | None] = mapped_column(Float)
    # 0.000 - 1.000 scores of the two marking methods, and how sure the AI is
    keyword_coverage: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    semantic_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    # Which answer points were matched (the spec's `points_covered`):
    # [{"answer_point_id": "...", "matched": true, "score": 0.8, "evidence": "..."}, ...]
    matched_points: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    feedback: Mapped[str | None] = mapped_column(Text)  # markdown
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), default=JobStatus.QUEUED)
    # A teacher's marks for the same answer, for the AI-accuracy report
    manual_marks: Mapped[float | None] = mapped_column(Float)
    manual_marked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    manual_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
