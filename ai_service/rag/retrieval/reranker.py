"""Optional second pass that re-orders the top results (placeholder)."""

from ai_service.rag.schemas import RetrievedChunk


async def rerank(
    query: str, chunks: list[RetrievedChunk], top_n: int | None = None
) -> list[RetrievedChunk]:
    """Today: keep the hybrid order.

    TODO(Samni): try an LLM reranker (ask Gemini to score relevance 0-10 for each chunk)
    or a cross-encoder, and compare with ai_service/evals before switching it on.
    """
    ordered = sorted(chunks, key=lambda c: c.score, reverse=True)
    return ordered[:top_n] if top_n else ordered
