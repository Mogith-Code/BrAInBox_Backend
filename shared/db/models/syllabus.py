"""Syllabus tree: units -> topics -> concepts. Owner: Keshomigha."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIM = 768  # must match the embedding provider's output size


class Unit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One of the 10 A/L Biology units."""

    __tablename__ = "units"

    number: Mapped[int] = mapped_column(Integer, unique=True)  # 1..10, also the display order
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # Relative share of this unit in past papers (used to spread diagnostic questions).
    # 1.0 for every unit until the real past-paper weights are entered (TBD).
    exam_weight: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")


class Topic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A topic inside a unit, e.g. "2.3 Cell membrane"."""

    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("unit_id", "number", name="uq_topics_unit_id_number"),)

    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[str] = mapped_column(String(20))  # e.g. "2.3"
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    # Topics removed from the current syllabus: kept for old data, skipped by the diagnostic.
    is_outdated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Concept(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single idea students must master, e.g. "active transport"."""

    __tablename__ = "concepts"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # Used to match questions/mistakes to concepts by meaning.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
