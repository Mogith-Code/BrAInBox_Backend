"""Question bank: questions, MCQ options, misconceptions and concept links. Owner: Udith."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ContentStatus, Difficulty, QuestionType


class Question(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "questions"

    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    question_type: Mapped[QuestionType] = mapped_column(str_enum(QuestionType))
    difficulty: Mapped[Difficulty] = mapped_column(str_enum(Difficulty), default=Difficulty.MEDIUM)
    stem: Mapped[str] = mapped_column(Text)  # the question text
    explanation: Mapped[str | None] = mapped_column(Text)
    marks: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(30), default="manual")  # manual|ai|past_paper
    year: Mapped[int | None] = mapped_column(Integer)  # past paper year
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.DRAFT
    )
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class Misconception(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A common wrong idea. Wrong MCQ options point to one, so mistakes can be explained."""

    __tablename__ = "misconceptions"

    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)


class MCQOption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcq_options"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(2))  # "1".."5" (A/L uses 5 options)
    text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    misconception_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("misconceptions.id", ondelete="SET NULL"), index=True
    )


class QuestionConcept(Base):
    """Many-to-many link: which concepts a question tests."""

    __tablename__ = "question_concepts"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
