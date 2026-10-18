"""Hybrid search = vector (meaning) search + full-text (keyword) search, scores merged.

Why both? Vector search finds paraphrases ("kidney filtering unit"), keyword search
finds exact Biology terms ("nephron", "plasmodesmata") that embeddings can blur.

Merged score = w * vector_score + (1 - w) * normalised keyword_score
"""

import uuid

from ai_service.rag.indexing.vector_store import SearchFilters, VectorStore
from ai_service.rag.schemas import RetrievedChunk


def merge_results(
    vector_hits: list[RetrievedChunk],
    keyword_hits: list[RetrievedChunk],
    vector_weight: float = 0.6,
) -> list[RetrievedChunk]:
    """Combine both result lists into one list sorted by the merged score."""
    max_keyword = max((h.keyword_score for h in keyword_hits), default=0.0) or 1.0
    merged: dict[uuid.UUID, RetrievedChunk] = {}

    for hit in vector_hits:
        merged[hit.chunk_id] = hit.model_copy()
    for hit in keyword_hits:
        if hit.chunk_id in merged:
            merged[hit.chunk_id].keyword_score = hit.keyword_score
        else:
            merged[hit.chunk_id] = hit.model_copy()

    for chunk in merged.values():
        vector_part = max(chunk.vector_score, 0.0)  # cosine similarity, ignore negatives
        keyword_part = chunk.keyword_score / max_keyword  # 0..1
        chunk.score = vector_weight * vector_part + (1 - vector_weight) * keyword_part

    return sorted(merged.values(), key=lambda c: c.score, reverse=True)


async def hybrid_search(
    store: VectorStore,
    query: str,
    query_embedding: list[float],
    filters: SearchFilters,
    k: int = 8,
    vector_weight: float = 0.6,
) -> list[RetrievedChunk]:
    candidates = k * 3  # fetch extra from each side, then keep the best k after merging
    vector_hits = await store.vector_search(query_embedding, filters, candidates)
    keyword_hits = await store.keyword_search(query, filters, candidates)
    return merge_results(vector_hits, keyword_hits, vector_weight)[:k]
