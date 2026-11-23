"""Big books are embedded in small, spaced batches, and a 429 waits instead of failing."""

import asyncio
from types import SimpleNamespace

import pytest
from google.genai import errors

from ai_service.providers import embeddings
from ai_service.providers.embeddings import GeminiEmbedder, make_batches, retry_seconds


class _Models:
    def __init__(self, fail_times: int = 0, code: int = 429) -> None:
        self.fail_times = fail_times
        self.code = code
        self.batches: list[list[str]] = []

    async def embed_content(self, *, model, contents, config):  # type: ignore[no-untyped-def]
        if self.fail_times:
            self.fail_times -= 1
            raise errors.ClientError(
                self.code, {"error": {"message": "Please retry in 7.5s.", "status": "LIMIT"}}
            )
        self.batches.append(list(contents))
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1]) for _ in contents])


def _embedder(models: _Models) -> GeminiEmbedder:
    embedder = GeminiEmbedder.__new__(GeminiEmbedder)
    embedder._client = SimpleNamespace(aio=SimpleNamespace(models=models))  # type: ignore[assignment]
    embedder.model, embedder.dim, embedder.daily_limit = "test", 768, 0
    embedder._next_send_at = 0.0
    return embedder


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:  # type: ignore[no-untyped-def]
    waited: list[float] = []

    async def no_wait(seconds: float) -> None:
        waited.append(seconds)

    async def no_quota(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    monkeypatch.setattr(embeddings, "use_quota", no_quota)
    return waited


def test_batches_keep_order_and_respect_both_limits() -> None:
    texts = ["a" * 300 for _ in range(7)]  # 100 estimated tokens each
    batches = make_batches(texts, max_items=3, max_tokens=250)
    assert [len(b) for b in batches] == [2, 2, 2, 1]
    assert [t for b in batches for t in b] == texts


def test_retry_time_comes_from_gemini() -> None:
    assert retry_seconds(Exception("Please retry in 30.5s.")) == 32.5
    assert retry_seconds(Exception("busy")) == embeddings.DEFAULT_RETRY_SECONDS


async def test_a_large_book_is_spaced_under_the_limit(sleeps) -> None:  # type: ignore[no-untyped-def]
    models = _Models()
    texts = ["x" * 3100 for _ in range(45)]  # about the size of Unit 5
    vectors = await _embedder(models).embed(texts)
    assert len(vectors) == 45
    assert all(sum(len(t) // 3 for t in batch) <= 6000 for batch in models.batches)
    assert len(models.batches) > 1
    assert len(sleeps) == len(models.batches) - 1


async def test_429_waits_and_retries(sleeps) -> None:  # type: ignore[no-untyped-def]
    models = _Models(fail_times=2)
    assert len(await _embedder(models).embed(["short text"])) == 1
    assert sleeps == [9.5, 9.5]


async def test_other_errors_still_stop(sleeps) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(errors.ClientError):
        await _embedder(_Models(fail_times=1, code=400)).embed(["short text"])
