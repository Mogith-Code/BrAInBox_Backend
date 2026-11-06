"""Store and search `document_chunks`.

Two implementations with the same methods:
  * PgVectorStore    - the real one (Postgres + pgvector, cosine distance, HNSW index;
                       keyword search with the `tsv` column + GIN index)
  * InMemoryVectorStore - a tiny pure-Python version for unit tests (no database)

Only the RAG layer uses this file. Pipelines call `rag.retrieval.retriever` instead.
"""

import math
import re
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.rag.schemas import Chunk, RetrievedChunk
from shared.db.models import DocumentChunk, SourceDocument
from shared.enums import DocumentStatus, SourceType


@dataclass
class DocumentRef:
    id: uuid.UUID
    title: str
    source_type: SourceType


@dataclass
class SearchFilters:
    unit_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    concept_id: uuid.UUID | None = None
    source_types: list[SourceType] | None = None


class VectorStore(Protocol):
    async def add_chunks(
        self, document: DocumentRef, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> int: ...

    async def delete_document_chunks(self, document_id: uuid.UUID) -> None: ...

    async def vector_search(
        self, embedding: list[float], filters: SearchFilters, limit: int
    ) -> list[RetrievedChunk]: ...

    async def keyword_search(
        self, query: str, filters: SearchFilters, limit: int
    ) -> list[RetrievedChunk]: ...


# --------------------------------------------------------------------------- Postgres


class PgVectorStore:
    """Real store. The caller owns the session and decides when to commit."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_chunks(
        self, document: DocumentRef, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        self.session.add_all(
            DocumentChunk(
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                heading_path=chunk.heading_path,
                page=chunk.page,
                unit_id=chunk.unit_id,
                topic_id=chunk.topic_id,
                concept_id=chunk.concept_id,
                embedding=embedding,
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        )
        await self.session.flush()
        return len(chunks)

    async def delete_document_chunks(self, document_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )

    def _base_query(self, *extra_columns: Any) -> Select[Any]:
        return (
            select(DocumentChunk, SourceDocument.title, SourceDocument.source_type, *extra_columns)
            .join(SourceDocument, SourceDocument.id == DocumentChunk.document_id)
            .where(SourceDocument.status == DocumentStatus.READY)
        )

    @staticmethod
    def _apply_filters(stmt: Select[Any], filters: SearchFilters) -> Select[Any]:
        if filters.unit_id:
            stmt = stmt.where(DocumentChunk.unit_id == filters.unit_id)
        if filters.topic_id:
            stmt = stmt.where(DocumentChunk.topic_id == filters.topic_id)
        if filters.concept_id:
            stmt = stmt.where(DocumentChunk.concept_id == filters.concept_id)
        if filters.source_types:
            stmt = stmt.where(SourceDocument.source_type.in_(filters.source_types))
        return stmt

    async def vector_search(
        self, embedding: list[float], filters: SearchFilters, limit: int
    ) -> list[RetrievedChunk]:
        distance = DocumentChunk.embedding.cosine_distance(embedding)
        stmt = self._base_query(distance.label("distance")).where(
            DocumentChunk.embedding.is_not(None)
        )
        stmt = self._apply_filters(stmt, filters).order_by(distance).limit(limit)
        rows = (await self.session.execute(stmt)).all()
        # cosine similarity = 1 - cosine distance
        return [
            _to_retrieved(row[0], row[1], row[2], vector_score=1.0 - float(row[3])) for row in rows
        ]

    async def keyword_search(
        self, query: str, filters: SearchFilters, limit: int
    ) -> list[RetrievedChunk]:
        # websearch_to_tsquery understands normal search text: words, "quoted phrases", -not
        ts_query = func.websearch_to_tsquery("english", query)
        rank = func.ts_rank_cd(DocumentChunk.tsv, ts_query)
        stmt = self._base_query(rank.label("rank")).where(DocumentChunk.tsv.op("@@")(ts_query))
        stmt = self._apply_filters(stmt, filters).order_by(rank.desc()).limit(limit)
        rows = (await self.session.execute(stmt)).all()
        return [_to_retrieved(row[0], row[1], row[2], keyword_score=float(row[3])) for row in rows]


def _to_retrieved(
    chunk: DocumentChunk,
    title: str,
    source_type: SourceType,
    vector_score: float = 0.0,
    keyword_score: float = 0.0,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        document_title=title,
        source_type=source_type,
        text=chunk.text,
        heading_path=chunk.heading_path,
        page=chunk.page,
        unit_id=chunk.unit_id,
        topic_id=chunk.topic_id,
        concept_id=chunk.concept_id,
        vector_score=vector_score,
        keyword_score=keyword_score,
    )


# --------------------------------------------------------------------------- In memory

_WORD_RE = re.compile(r"[a-z0-9]+")


class InMemoryVectorStore:
    """Same behaviour as PgVectorStore, kept in a Python list. For tests only."""

    def __init__(self) -> None:
        self.rows: list[tuple[RetrievedChunk, list[float]]] = []

    async def add_chunks(
        self, document: DocumentRef, chunks: list[Chunk], embeddings: list[list[float]]
    ) -> int:
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            item = RetrievedChunk(
                chunk_id=uuid.uuid4(),
                document_id=document.id,
                document_title=document.title,
                source_type=document.source_type,
                text=chunk.text,
                heading_path=chunk.heading_path,
                page=chunk.page,
                unit_id=chunk.unit_id,
                topic_id=chunk.topic_id,
                concept_id=chunk.concept_id,
            )
            self.rows.append((item, embedding))
        return len(chunks)

    async def delete_document_chunks(self, document_id: uuid.UUID) -> None:
        self.rows = [(c, e) for c, e in self.rows if c.document_id != document_id]

    def _matches(self, chunk: RetrievedChunk, f: SearchFilters) -> bool:
        return (
            (f.unit_id is None or chunk.unit_id == f.unit_id)
            and (f.topic_id is None or chunk.topic_id == f.topic_id)
            and (f.concept_id is None or chunk.concept_id == f.concept_id)
            and (not f.source_types or chunk.source_type in f.source_types)
        )

    async def vector_search(
        self, embedding: list[float], filters: SearchFilters, limit: int
    ) -> list[RetrievedChunk]:
        scored = [
            c.model_copy(update={"vector_score": _cosine(embedding, e)})
            for c, e in self.rows
            if self._matches(c, filters)
        ]
        return sorted(scored, key=lambda c: c.vector_score, reverse=True)[:limit]

    async def keyword_search(
        self, query: str, filters: SearchFilters, limit: int
    ) -> list[RetrievedChunk]:
        terms = set(_WORD_RE.findall(query.lower()))
        results = []
        for chunk, _ in self.rows:
            if not self._matches(chunk, filters) or not terms:
                continue
            words = set(_WORD_RE.findall(f"{chunk.heading_path or ''} {chunk.text}".lower()))
            score = len(terms & words) / len(terms)
            if score > 0:
                results.append(chunk.model_copy(update={"keyword_score": score}))
        return sorted(results, key=lambda c: c.keyword_score, reverse=True)[:limit]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
