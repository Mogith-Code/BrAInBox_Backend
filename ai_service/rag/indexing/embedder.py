"""Batch-embed chunks with the configured embedding provider (real or fake)."""

from ai_service.providers import get_embedder
from ai_service.providers.base import EmbeddingProvider
from ai_service.rag.schemas import Chunk


def embedding_text(chunk: Chunk) -> str:
    """Include the heading path so the vector also knows *where* the text is from."""
    return f"{chunk.heading_path}\n{chunk.text}" if chunk.heading_path else chunk.text


async def embed_chunks(
    chunks: list[Chunk], embedder: EmbeddingProvider | None = None
) -> list[list[float]]:
    embedder = embedder or get_embedder()
    return await embedder.embed([embedding_text(c) for c in chunks], task="document")


async def embed_query(query: str, embedder: EmbeddingProvider | None = None) -> list[float]:
    embedder = embedder or get_embedder()
    vectors = await embedder.embed([query], task="query")
    return vectors[0]
