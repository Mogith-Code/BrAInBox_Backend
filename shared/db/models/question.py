"""Question bank: questions, MCQ options, misconceptions and concept links. Owner: Udith."""

import uuid
from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import (
    EMBEDDING_DIM,
    AIGeneratedMixin,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    str_enum,
)
from shared.enums import ContentStatus, Difficulty, PaperPart, QuestionType


class Question(UUIDPrimaryKeyMixin, TimestampMixin, AIGeneratedMixin, Base):
    """One question (MCQ, structured or essay) in the bank. Owner: Udith."""

    __tablename__ = "questions"
    __table_args__ = (
        # A past-paper question is identified by year + part + number.
        Index(
            "uq_questions_past_paper_number",
            "year",
            "paper_part",
            "question_number",
            unique=True,
            postgresql_where=text("source = 'past_paper'"),
        ),
        Index("ix_questions_unit_type_status", "unit_id", "question_type", "status"),
        Index(
            "ix_questions_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        CheckConstraint("source IN ('past_paper', 'ai', 'admin', 'manual')", name="source"),
        CheckConstraint("source <> 'past_paper' OR year IS NOT NULL", name="past_paper_year"),
        CheckConstraint("marks > 0", name="marks_positive"),
    )

    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units.id", ondelete="RESTRICT"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="RESTRICT"), index=True
    )
    question_type: Mapped[QuestionType] = mapped_column(str_enum(QuestionType))
    difficulty: Mapped[Difficulty] = mapped_column(str_enum(Difficulty), default=Difficulty.MEDIUM)
    stem: Mapped[str] = mapped_column(Text)  # the question text (markdown, the spec's `stem_md`)
    stem_image_path: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    marks: Mapped[int] = mapped_column(Integer, default=1)
    # QuestionOrigin value: past_paper | ai | admin | manual (the spec's `origin`)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    year: Mapped[int | None] = mapped_column(Integer)  # past paper year
    paper_part: Mapped[PaperPart | None] = mapped_column(str_enum(PaperPart))
    question_number: Mapped[str | None] = mapped_column(String(10))  # e.g. "23" or "5(b)"
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.DRAFT
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(64))


class Misconception(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A common wrong idea. Wrong MCQ options point to one, so mistakes can be explained."""

    __tablename__ = "misconceptions"

    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    correction_md: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class MCQOption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One of the 5 options of an MCQ, labelled "A".."E". Owner: Udith."""

    __tablename__ = "mcq_options"
    __table_args__ = (
        UniqueConstraint("question_id", "label", name="uq_mcq_options_question_label"),
        # At most one correct option per question (the API checks "at least one").
        Index(
            "uq_mcq_options_one_correct",
            "question_id",
            unique=True,
            postgresql_where=text("is_correct"),
        ),
        CheckConstraint("label IN ('A', 'B', 'C', 'D', 'E')", name="label"),
    )

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(2))  # "A".."E" (A/L MCQs have 5 options)
    text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    misconception_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("misconceptions.id", ondelete="SET NULL"), index=True
    )
    explanation_md: Mapped[str | None] = mapped_column(Text)  # why this option is right/wrong


class QuestionConcept(Base):
    """Many-to-many link: which concepts a question tests. Owner: Udith."""

    __tablename__ = "question_concepts"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    weight: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), default=Decimal("1.0"), server_default="1.0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
