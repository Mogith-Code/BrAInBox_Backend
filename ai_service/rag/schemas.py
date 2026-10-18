"""Data shapes used by the RAG layer."""

import uuid

from pydantic import BaseModel, Field

from shared.enums import SourceType


class Chunk(BaseModel):
    """A piece of a document, before it is stored."""

    chunk_index: int
    text: str
    heading_path: str | None = None  # e.g. "Unit 2 > Cell membrane > Active transport"
    page: int | None = None
    token_count: int = 0
    # Syllabus position (filled by ingestion/metadata.py)
    unit_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    concept_id: uuid.UUID | None = None


class RetrievalQuery(BaseModel):
    query: str
    unit_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    concept_id: uuid.UUID | None = None
    source_types: list[SourceType] | None = None  # None = all source types
    k: int = Field(default=8, ge=1, le=50)


class RetrievedChunk(BaseModel):
    """A chunk returned by search, with its source (for citations) and scores."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    source_type: SourceType
    text: str
    heading_path: str | None = None
    page: int | None = None
    unit_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    concept_id: uuid.UUID | None = None
    vector_score: float = 0.0  # cosine similarity (higher = closer)
    keyword_score: float = 0.0  # Postgres full-text rank
    score: float = 0.0  # final merged score
