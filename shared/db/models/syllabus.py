<<<<<<< Updated upstream
"""Syllabus tree: units -> topics -> concepts. Owner: Keshomigha.

Deleting cascades only DOWN the tree (unit -> topics -> concepts). Content that points at a
topic or concept (notes, questions, visuals...) uses ON DELETE RESTRICT, so a syllabus row
that has content cannot be deleted by accident. Mark it `is_outdated` instead.
=======
"""Syllabus tree: subjects -> units -> topics -> concepts (sub-topics). Owner: Keshomigha.

Every level has a stable public `code` set by scripts/seed_syllabus.py, e.g. subject "biology",
unit "u6", topic "bio-6.1", concept "bio-6.1.1". The app navigates with these codes; the UUID `id`
stays the primary key that every other table references.
>>>>>>> Stashed changes
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import EMBEDDING_DIM, Base, TimestampMixin, UUIDPrimaryKeyMixin

__all__ = ["EMBEDDING_DIM", "Concept", "Topic", "Unit"]


class Subject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A subject, e.g. "Biology" at "G.C.E. A/L"."""

    __tablename__ = "subjects"

    code: Mapped[str] = mapped_column(String(50), unique=True)  # e.g. "biology"
    name: Mapped[str] = mapped_column(String(100))
    level: Mapped[str] = mapped_column(String(50))  # e.g. "G.C.E. A/L"


class Unit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One of the 10 A/L Biology units. Owner: Keshomigha."""

    __tablename__ = "units"

<<<<<<< Updated upstream
    # 1..10: the unit's code AND its display order (the spec's `code` / `order_index`).
    number: Mapped[int] = mapped_column(Integer, unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # Relative share of this unit in past papers (the spec's `past_paper_weight`; used to
    # spread diagnostic questions). 1.0 for every unit until the real weights are entered (TBD).
    exam_weight: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")
    is_outdated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
=======
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str | None] = mapped_column(String(20), unique=True)  # e.g. "u6"
    number: Mapped[int] = mapped_column(Integer, unique=True)  # 1..10, also the display order
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    periods: Mapped[int | None] = mapped_column(Integer)  # teaching periods in the NIE syllabus
    icon: Mapped[str | None] = mapped_column(String(50))  # icon name used by the app, e.g. "dna"
>>>>>>> Stashed changes


class Topic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A topic inside a unit, e.g. "2.3 Cell membrane". Owner: Keshomigha."""

    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("unit_id", "number", name="uq_topics_unit_id_number"),)

    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("units.id", ondelete="CASCADE"), index=True
    )
<<<<<<< Updated upstream
    number: Mapped[str] = mapped_column(String(20))  # e.g. "2.3" (the spec's `code`)
=======
    code: Mapped[str | None] = mapped_column(String(30), unique=True)  # e.g. "bio-6.1"
    number: Mapped[str] = mapped_column(String(20))  # e.g. "2.3"
>>>>>>> Stashed changes
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    # Topics removed from the current syllabus: kept for old data, skipped by the diagnostic.
    is_outdated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Concept(UUIDPrimaryKeyMixin, TimestampMixin, Base):
<<<<<<< Updated upstream
    """A single idea students must master, e.g. "active transport". Owner: Keshomigha."""
=======
    """A single idea students must master, e.g. "active transport".

    The syllabus sub-topics are stored here (the API calls them `subtopics`).
    """
>>>>>>> Stashed changes

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
<<<<<<< Updated upstream
    code: Mapped[str | None] = mapped_column(String(20), unique=True)  # e.g. "6.2.1"
    name: Mapped[str] = mapped_column(String(200))  # the spec's `title`
    description: Mapped[str | None] = mapped_column(Text)
    learning_outcome: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_outdated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
=======
    code: Mapped[str | None] = mapped_column(String(40), unique=True)  # e.g. "bio-6.1.1"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
>>>>>>> Stashed changes
    # Used to match questions/mistakes to concepts by meaning.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(64))
