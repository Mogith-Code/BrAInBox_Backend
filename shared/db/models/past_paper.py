"""Past papers uploaded by admins, and the questions extracted from them. Owner: Udith.

The PDF is stored at past_papers/{past_paper_id}.pdf (and its marking scheme, if given, at
past_papers/{past_paper_id}-scheme.pdf). An EXTRACT_PAST_PAPER job reads it (text layer, OCR for
scanned pages) and splits it into questions; an admin then adds the model answer + keywords.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Extraction states (stored); the API shows "running" for queued too, and
# "low_confidence" for a finished paper with unsure questions.
EXTRACTION_STATES = ("queued", "running", "done", "failed")
PAPER_TYPES = ("paper_1_mcq", "paper_2_structured")


class PastPaper(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "past_papers"
    __table_args__ = (
        UniqueConstraint("year", "paper_type", name="uq_past_papers_year_type"),
        CheckConstraint("year BETWEEN 1990 AND 2100", name="year_range"),
        CheckConstraint("paper_type IN ('paper_1_mcq', 'paper_2_structured')", name="paper_type"),
        CheckConstraint(
            "extraction_status IN ('queued', 'running', 'done', 'failed')",
            name="extraction_status",
        ),
        CheckConstraint("progress BETWEEN 0 AND 1", name="progress_range"),
    )

    year: Mapped[int] = mapped_column(Integer)
    paper_type: Mapped[str] = mapped_column(String(30))
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer)
    scheme_path: Mapped[str | None] = mapped_column(String(500))  # marking scheme PDF
    extraction_status: Mapped[str] = mapped_column(
        String(20), default="queued", server_default="queued"
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    # True when the paper covers topics that are no longer in the syllabus.
    outdated_syllabus: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_jobs.id", ondelete="SET NULL"), index=True
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class PastPaperQuestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One question (or sub-question, e.g. "Q3 (b)") extracted from a past paper."""

    __tablename__ = "past_paper_questions"
    __table_args__ = (
        Index("ix_past_paper_questions_paper_position", "past_paper_id", "position"),
        CheckConstraint("ocr_confidence BETWEEN 0 AND 1", name="ocr_confidence_range"),
    )

    past_paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("past_papers.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)  # order in the paper, from 1
    label: Mapped[str] = mapped_column(String(30))  # "Q12" or "Q3 (b)"
    marks: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)  # 0-1, how readable the text is
    model_answer: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), default=list, server_default="{}"
    )
    suggested_keywords: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), default=list, server_default="{}"
    )
