"""Embedding adapter: Gemini embeddings (768 dimensions, matching vector(768) in the DB)."""

from ai_service.config import get_settings
from ai_service.daily_limits import use_quota


class GeminiEmbedder:
    name = "gemini-embeddings"

    def __init__(self, api_key: str, model: str, dim: int = 768, daily_limit: int = 0):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.dim = dim
        self.daily_limit = daily_limit  # requests per day (one per batch); 0 = no cap

    async def embed(self, texts: list[str], *, task: str = "document") -> list[list[float]]:
        from google.genai import types

        task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
        batch_size = get_settings().EMBEDDING_BATCH_SIZE
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            await use_quota("gemini", "embed", self.model, self.daily_limit)
            result = await self._client.aio.models.embed_content(
                model=self.model,
                contents=batch,  # type: ignore[arg-type]
                config=types.EmbedContentConfig(
                    task_type=task_type, output_dimensionality=self.dim
                ),
            )
            vectors.extend(list(e.values or []) for e in (result.embeddings or []))
        # TODO(Samni): normalise vectors if the model does not (needed for dims < 3072).
        return vectors
