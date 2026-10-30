"""Syllabus tree: units -> topics -> concepts. Owner: Keshomigha.

Deleting cascades only DOWN the tree (unit -> topics -> concepts). Content that points at a
topic or concept (notes, questions, visuals...) uses ON DELETE RESTRICT, so a syllabus row
that has content cannot be deleted by accident. Mark it `is_outdated` instead.
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import EMBEDDING_DIM, Base, TimestampMixin, UUIDPrimaryKeyMixin

__all__ = ["EMBEDDING_DIM", "Concept", "Topic", "Unit"]


class Unit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One of the 10 A/L Biology units. Owner: Keshomigha."""

    __tablename__ = "units"

    # 1..10: the unit's code AND its display order (the spec's `code` / `order_index`).
    number: Mapped[int] = mapped_column(Integer, unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # Relative share of this unit in past papers (the spec's `past_paper_weight`; used to
    # spread diagnostic questions). 1.0 for every unit until the real weights are entered (TBD).
    exam_weight: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")
    is_outdated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Topic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A topic inside a unit, e.g. "2.3 Cell membrane". Owner: Keshomigha."""

    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("unit_id", "number", name="uq_topics_unit_id_number"),)

    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[str] = mapped_column(String(20))  # e.g. "2.3" (the spec's `code`)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    # Topics removed from the current syllabus: kept for old data, skipped by the diagnostic.
    is_outdated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Concept(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single idea students must master, e.g. "active transport". Owner: Keshomigha."""

    __tablename__ = "concepts"
    __table_args__ = (
        # Approximate nearest-neighbour index for cosine similarity.
        Index(
            "ix_concepts_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str | None] = mapped_column(String(20), unique=True)  # e.g. "6.2.1"
    name: Mapped[str] = mapped_column(String(200))  # the spec's `title`
    description: Mapped[str | None] = mapped_column(Text)
    learning_outcome: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_outdated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Used to match questions/mistakes to concepts by meaning.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(64))
