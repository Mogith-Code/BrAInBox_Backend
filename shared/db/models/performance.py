"""Student performance: mistakes, mastery per concept / unit, study activity. Owner: Keshomigha."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import MistakeType


class Mistake(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One mistake a student made (wrong answer + why). Owner: Keshomigha."""

    __tablename__ = "mistakes"
    __table_args__ = (
        Index("ix_mistakes_user_concept", "user_id", "concept_id"),
        Index("ix_mistakes_user_open", "user_id", postgresql_where=text("resolved_at IS NULL")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("questions.id", ondelete="SET NULL"), index=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), index=True
    )
    response_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("responses.id", ondelete="SET NULL"), index=True
    )
    misconception_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("misconceptions.id", ondelete="SET NULL"), index=True
    )
    mistake_type: Mapped[MistakeType] = mapped_column(str_enum(MistakeType))
    note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConceptMastery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How well one student knows one concept (0.0 - 1.0). Owner: Keshomigha."""

    __tablename__ = "concept_mastery"
    __table_args__ = (
        UniqueConstraint("user_id", "concept_id", name="uq_concept_mastery_user_concept"),
        CheckConstraint("mastery_score BETWEEN 0 AND 1", name="mastery_score_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), index=True
    )
    mastery_score: Mapped[float] = mapped_column(Float, default=0.0)
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UnitMastery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Mastery (0-100) of one unit for one student, as a HISTORY of snapshots.

    Every diagnostic (later: quizzes, papers) adds new rows instead of updating old ones.
    Current mastery = the newest row per unit; "7 days ago" = the newest row older than 7 days.
    That is what the home screen's weekly change ("+4% wk") is computed from.
    """

    __tablename__ = "unit_mastery"
    __table_args__ = (
        Index("ix_unit_mastery_user_unit_created", "user_id", "unit_id", "created_at"),
        CheckConstraint("mastery BETWEEN 0 AND 100", name="mastery_range"),
        CheckConstraint("source IN ('diagnostic', 'practice', 'exam', 'quiz')", name="source"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units.id", ondelete="CASCADE"), index=True
    )
    mastery: Mapped[int] = mapped_column(Integer)  # 0-100
    # MasterySource value: diagnostic | practice | exam | quiz
    source: Mapped[str] = mapped_column(String(20), default="diagnostic")


class MasterySnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A student's overall mastery (0-100) on one day, for weekly progress. Owner: Keshomigha.

    Same 0-100 scale as unit_mastery (the app shows percentages).
    """

    __tablename__ = "mastery_snapshots"
    __table_args__ = (
        UniqueConstraint("user_id", "snapshot_date", name="uq_mastery_snapshots_user_date"),
        CheckConstraint("overall_mastery BETWEEN 0 AND 100", name="overall_mastery_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date)
    overall_mastery: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    # {"<unit_id>": 62, ...}
    unit_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class StudyActivity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per student per day they studied (answered a question, finished a plan item...).

    Used for the home screen streak. The date is the student's local date (Sri Lanka time).
    """

    __tablename__ = "study_activity"
    __table_args__ = (
        UniqueConstraint("user_id", "activity_date", name="uq_study_activity_user_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    activity_date: Mapped[date] = mapped_column(Date)
    minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    actions_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
