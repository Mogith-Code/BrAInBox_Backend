"""Embedding adapter: Gemini embeddings (768 dimensions, matching vector(768) in the DB).

The free plan allows 30,000 tokens a minute, so big books are sent in small batches with a
pause between them. If Gemini still answers 429 (too fast), we wait as long as it asks and retry.
"""

import asyncio
import logging
import re
import time
from typing import Any

from ai_service.config import get_settings
from ai_service.daily_limits import use_quota

logger = logging.getLogger(__name__)

MAX_RATE_LIMIT_RETRIES = 5
DEFAULT_RETRY_SECONDS = 35.0  # used when Gemini doesn't say how long to wait
_RETRY_IN_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)


def estimate_tokens(text: str) -> int:
    """A safe over-estimate: English is usually about 4 characters per token."""
    return max(1, len(text) // 3)


def make_batches(texts: list[str], max_items: int, max_tokens: int) -> list[list[str]]:
    """Split texts in order, keeping each batch under both limits."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for text in texts:
        tokens = estimate_tokens(text)
        if current and (len(current) >= max_items or current_tokens + tokens > max_tokens):
            batches.append(current)
            current, current_tokens = [], 0
        current.append(text)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


def retry_seconds(error: Exception) -> float:
    """How long Gemini asked us to wait, plus a small safety margin."""
    match = _RETRY_IN_RE.search(str(error))
    return float(match.group(1)) + 2 if match else DEFAULT_RETRY_SECONDS


class GeminiEmbedder:
    name = "gemini-embeddings"

    def __init__(self, api_key: str, model: str, dim: int = 768, daily_limit: int = 0):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.dim = dim
        self.daily_limit = daily_limit  # requests per day (one per batch); 0 = no cap
        self._next_send_at = 0.0  # time.monotonic() when the next batch may be sent

    async def _wait_for_room(self, tokens: int, tokens_per_minute: int) -> None:
        """Space the batches out so we stay under the per-minute limit."""
        if tokens_per_minute <= 0:
            return
        now = time.monotonic()
        if self._next_send_at > now:
            await asyncio.sleep(self._next_send_at - now)
            now = self._next_send_at
        self._next_send_at = now + tokens / tokens_per_minute * 60

    async def _send(self, batch: list[str], config: Any) -> Any:
        """One batch. A 429 waits and tries again; any other error stops the import."""
        from google.genai import errors

        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            await use_quota("gemini", "embed", self.model, self.daily_limit)
            try:
                return await self._client.aio.models.embed_content(
                    model=self.model,
                    contents=batch,  # type: ignore[arg-type]
                    config=config,
                )
            except errors.ClientError as exc:
                if exc.code != 429 or attempt == MAX_RATE_LIMIT_RETRIES:
                    raise
                seconds = retry_seconds(exc)
                logger.warning("Gemini embedding limit reached, waiting %.0f seconds", seconds)
                await asyncio.sleep(seconds)
        raise RuntimeError("unreachable")

    async def embed(self, texts: list[str], *, task: str = "document") -> list[list[float]]:
        from google.genai import types

        settings = get_settings()
        task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
        config = types.EmbedContentConfig(task_type=task_type, output_dimensionality=self.dim)
        per_minute = settings.EMBEDDING_TOKENS_PER_MINUTE
        # A quarter of the minute's allowance per batch keeps the pauses short and even.
        max_tokens = per_minute // 4 if per_minute > 0 else sum(map(estimate_tokens, texts))
        vectors: list[list[float]] = []
        for batch in make_batches(texts, settings.EMBEDDING_BATCH_SIZE, max_tokens):
            await self._wait_for_room(sum(map(estimate_tokens, batch)), per_minute)
            result = await self._send(batch, config)
            vectors.extend(list(e.values or []) for e in (result.embeddings or []))
        # TODO(Samni): normalise vectors if the model does not (needed for dims < 3072).
        return vectors
