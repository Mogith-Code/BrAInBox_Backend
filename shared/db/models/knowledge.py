"""Marking knowledge base: model answers -> answer points -> keywords. Owner: Keshomigha."""

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ContentStatus


class ModelAnswer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "model_answers"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    answer_text: Mapped[str] = mapped_column(Text)
    total_marks: Mapped[float] = mapped_column(Float, default=0)
    source: Mapped[str | None] = mapped_column(String(100))  # e.g. "marking scheme 2023"
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.DRAFT
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class AnswerPoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One marking point of a model answer (e.g. "mentions ATP is used" = 1 mark)."""

    __tablename__ = "answer_points"

    model_answer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_answers.id", ondelete="CASCADE"), index=True
    )
    point_text: Mapped[str] = mapped_column(Text)
    marks: Mapped[float] = mapped_column(Float, default=1)
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class Keyword(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A keyword (with synonyms) that shows an answer point was made."""

    __tablename__ = "keywords"

    answer_point_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("answer_points.id", ondelete="CASCADE"), index=True
    )
    keyword: Mapped[str] = mapped_column(String(100))
    synonyms: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), default=list, server_default="{}"
    )
    weight: Mapped[float] = mapped_column(Float, default=1.0)
