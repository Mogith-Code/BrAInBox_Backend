"""Student performance: recorded mistakes and mastery per concept. Owner: Keshomigha."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import MistakeType


class Mistake(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mistakes"

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


class ConceptMastery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How well one student knows one concept (0.0 - 1.0)."""

    __tablename__ = "concept_mastery"
    __table_args__ = (
        UniqueConstraint("user_id", "concept_id", name="uq_concept_mastery_user_concept"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), index=True
    )
    mastery_score: Mapped[float] = mapped_column(Float, default=0.0)
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
