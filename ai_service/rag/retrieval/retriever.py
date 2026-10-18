"""THE entry point for grounding. Pipelines call `retrieve(...)`, nothing else.

from ai_service.rag.retrieval.retriever import retrieve
from ai_service.rag.context_builder import build_context

chunks = await retrieve("active transport", topic_id=topic_id, k=6)
context = build_context(chunks)          # -> context.text, context.citations
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.config import get_settings
from ai_service.providers.base import EmbeddingProvider
from ai_service.rag.indexing.embedder import embed_query
from ai_service.rag.indexing.vector_store import PgVectorStore, SearchFilters, VectorStore
from ai_service.rag.retrieval.hybrid import hybrid_search
from ai_service.rag.retrieval.reranker import rerank
from ai_service.rag.schemas import RetrievalQuery, RetrievedChunk
from shared.db.session import SessionLocal
from shared.enums import SourceType


class Retriever:
    def __init__(
        self,
        store: VectorStore,
        embedder: EmbeddingProvider | None = None,
        vector_weight: float | None = None,
    ):
        self.store = store
        self.embedder = embedder
        self.vector_weight = (
            get_settings().RAG_VECTOR_WEIGHT if vector_weight is None else vector_weight
        )

    async def retrieve(self, q: RetrievalQuery) -> list[RetrievedChunk]:
        filters = SearchFilters(
            unit_id=q.unit_id,
            topic_id=q.topic_id,
            concept_id=q.concept_id,
            source_types=q.source_types,
        )
        query_embedding = await embed_query(q.query, self.embedder)
        hits = await hybrid_search(
            self.store, q.query, query_embedding, filters, k=q.k, vector_weight=self.vector_weight
        )
        return await rerank(q.query, hits, top_n=q.k)


async def retrieve(
    query: str,
    unit_id: uuid.UUID | None = None,
    topic_id: uuid.UUID | None = None,
    source_types: list[SourceType] | None = None,
    k: int = 8,
    *,
    concept_id: uuid.UUID | None = None,
    session: AsyncSession | None = None,
) -> list[RetrievedChunk]:
    """Search the approved source documents. Opens its own DB session if none is given."""
    q = RetrievalQuery(
        query=query,
        unit_id=unit_id,
        topic_id=topic_id,
        concept_id=concept_id,
        source_types=source_types,
        k=k,
    )
    if session is not None:
        return await Retriever(PgVectorStore(session)).retrieve(q)
    async with SessionLocal() as own_session:
        return await Retriever(PgVectorStore(own_session)).retrieve(q)
