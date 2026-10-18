"""Provider factory. Pipelines call these functions instead of creating SDK clients.

    llm = get_llm()
    vectors = await get_embedder().embed(["text"])

When USE_FAKE_AI=true (or GEMINI_API_KEY is empty) the deterministic fakes are returned.
Tests can call `set_providers(...)` to inject their own fakes.
"""

import logging
from typing import Any

from ai_service.config import get_settings
from ai_service.providers.base import (
    EmbeddingProvider,
    ImageProvider,
    LLMProvider,
    OCRProvider,
    StorageProvider,
)
from ai_service.providers.fakes import (
    FakeEmbedder,
    FakeImageGenerator,
    FakeLLM,
    FakeOCR,
    FakeStorage,
)

logger = logging.getLogger(__name__)

_cache: dict[str, Any] = {}


def _get(kind: str, build_real: Any, build_fake: Any) -> Any:
    if kind not in _cache:
        if get_settings().use_fakes:
            _cache[kind] = build_fake()
        else:
            try:
                _cache[kind] = build_real()
            except Exception:
                # Missing SDK or credentials: fall back to the fake so the service still starts.
                logger.exception("Could not create real %s provider; using the fake", kind)
                _cache[kind] = build_fake()
    return _cache[kind]


def get_llm() -> LLMProvider:
    from ai_service.providers.llm_gemini import GeminiLLM

    s = get_settings()
    return _get(
        "llm", lambda: GeminiLLM(s.GEMINI_API_KEY, s.GEMINI_MODEL, s.GEMINI_FALLBACK_MODEL), FakeLLM
    )  # type: ignore[no-any-return]


def get_embedder() -> EmbeddingProvider:
    from ai_service.providers.embeddings import GeminiEmbedder

    s = get_settings()
    return _get(  # type: ignore[no-any-return]
        "embedder",
        lambda: GeminiEmbedder(s.GEMINI_API_KEY, s.GEMINI_EMBEDDING_MODEL, s.EMBEDDING_DIM),
        lambda: FakeEmbedder(s.EMBEDDING_DIM),
    )


def get_ocr() -> OCRProvider:
    from ai_service.providers.ocr_vision import VisionOCR

    return _get("ocr", VisionOCR, FakeOCR)  # type: ignore[no-any-return]


def get_image_generator() -> ImageProvider:
    from ai_service.providers.image_gen import GeminiImageGenerator

    s = get_settings()
    return _get(  # type: ignore[no-any-return]
        "image", lambda: GeminiImageGenerator(s.GEMINI_API_KEY, s.IMAGE_MODEL), FakeImageGenerator
    )


def get_storage() -> StorageProvider:
    from ai_service.providers.storage import FirebaseStorage

    s = get_settings()
    return _get(  # type: ignore[no-any-return]
        "storage", lambda: FirebaseStorage(s.STORAGE_BUCKET, s.FIREBASE_PROJECT_ID), FakeStorage
    )


def provider_names() -> dict[str, str]:
    """Which provider is active for each kind (shown on /health)."""
    return {
        "llm": getattr(get_llm(), "name", "?"),
        "embedder": getattr(get_embedder(), "name", "?"),
    }


def set_providers(**providers: Any) -> None:
    """Override providers, e.g. set_providers(llm=FakeLLM()). Used by tests."""
    _cache.update(providers)


def reset_providers() -> None:
    _cache.clear()
