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
    DiagramRenderer,
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
        "llm",
        lambda: GeminiLLM(
            s.GEMINI_API_KEY, s.GEMINI_MODEL, s.GEMINI_FALLBACK_MODEL, s.GEMINI_DAILY_LIMIT
        ),
        FakeLLM,
    )  # type: ignore[no-any-return]


def get_embedder() -> EmbeddingProvider:
    from ai_service.providers.embeddings import GeminiEmbedder

    s = get_settings()
    return _get(  # type: ignore[no-any-return]
        "embedder",
        lambda: GeminiEmbedder(
            s.GEMINI_API_KEY, s.GEMINI_EMBEDDING_MODEL, s.EMBEDDING_DIM, s.EMBEDDING_DAILY_LIMIT
        ),
        lambda: FakeEmbedder(s.EMBEDDING_DIM),
    )


def get_ocr() -> OCRProvider:
    from ai_service.providers.ocr_vision import VisionOCR

    limit = get_settings().OCR_DAILY_LIMIT
    return _get("ocr", lambda: VisionOCR(limit), FakeOCR)  # type: ignore[no-any-return]


def get_image_generator() -> ImageProvider:
    """The image model chosen with IMAGE_PROVIDER ("cloudflare" = free, or "gemini" = paid).

    The fake is used when USE_FAKE_AI=true or the chosen provider has no key. Real pictures
    are capped by IMAGE_DAILY_LIMIT (ai_service/daily_limits.py).
    """
    from ai_service.providers.image_gen import CloudflareImageGenerator, GeminiImageGenerator

    s = get_settings()
    if "image" not in _cache:
        provider = s.IMAGE_PROVIDER.strip().lower()
        if provider == "cloudflare":
            has_keys = bool(s.CLOUDFLARE_ACCOUNT_ID and s.CLOUDFLARE_API_TOKEN)
            if s.USE_FAKE_AI or not has_keys:
                _cache["image"] = FakeImageGenerator()
            else:
                _cache["image"] = CloudflareImageGenerator(
                    s.CLOUDFLARE_ACCOUNT_ID,
                    s.CLOUDFLARE_API_TOKEN,
                    s.CLOUDFLARE_IMAGE_MODEL,
                    timeout=s.IMAGE_TIMEOUT_SECONDS,
                    daily_limit=s.IMAGE_DAILY_LIMIT,
                )
        elif provider == "gemini":
            _get(
                "image",
                lambda: GeminiImageGenerator(s.GEMINI_API_KEY, s.IMAGE_MODEL, s.IMAGE_DAILY_LIMIT),
                FakeImageGenerator,
            )
        else:
            raise ValueError(
                f"Unknown IMAGE_PROVIDER: {s.IMAGE_PROVIDER!r} (use gemini or cloudflare)"
            )
    return _cache["image"]  # type: ignore[no-any-return]


async def can_draw_illustrations() -> bool:
    """True if an illustration can be drawn now; otherwise visuals use (free) Mermaid diagrams.

    No: no real image provider is set up (no key) while real AI is on, so we would only
    have the fake 1x1 picture; or today's free pictures (IMAGE_DAILY_LIMIT) are used up.
    """
    from ai_service.daily_limits import has_quota

    s = get_settings()
    generator = get_image_generator()
    quota_provider = getattr(generator, "quota_provider", None)
    if quota_provider is None:  # the fake: fine for tests / offline dev, never for students
        return s.use_fakes
    return await has_quota(quota_provider, "image", s.IMAGE_DAILY_LIMIT)


def get_diagram_renderer() -> DiagramRenderer:
    """Kroki (Mermaid -> PNG). Tests (ENVIRONMENT=test) get a fake, so they never use the network.

    Kroki is free and needs no key, so dev uses the real one even with USE_FAKE_AI=true.
    """
    from ai_service.providers.diagram_renderer import FakeDiagramRenderer, KrokiRenderer

    s = get_settings()
    if "diagram" not in _cache:
        if s.ENVIRONMENT == "test":
            _cache["diagram"] = FakeDiagramRenderer()
        else:
            _cache["diagram"] = KrokiRenderer(s.KROKI_URL, timeout=s.KROKI_TIMEOUT_SECONDS)
    return _cache["diagram"]  # type: ignore[no-any-return]


def get_storage() -> StorageProvider:
    """Firebase Storage when STORAGE_BUCKET is set. Without a bucket: the in-memory fake in tests,
    the local folder shared with the api in dev (so uploads work without Firebase)."""
    from ai_service.providers.storage import FirebaseStorage, LocalStorage

    s = get_settings()
    if "storage" not in _cache:
        if s.STORAGE_BUCKET:
            _cache["storage"] = FirebaseStorage(s.STORAGE_BUCKET, s.FIREBASE_PROJECT_ID)
        elif s.ENVIRONMENT == "test":
            _cache["storage"] = FakeStorage()
        elif s.ENVIRONMENT == "prod":
            raise RuntimeError("STORAGE_BUCKET must be set in prod")
        else:
            _cache["storage"] = LocalStorage(s.LOCAL_STORAGE_DIR)
    return _cache["storage"]  # type: ignore[no-any-return]


def provider_names() -> dict[str, str]:
    """Which provider is active for each kind (shown on /health)."""
    return {
        "llm": getattr(get_llm(), "name", "?"),
        "embedder": getattr(get_embedder(), "name", "?"),
        "image": getattr(get_image_generator(), "name", "?"),
    }


def set_providers(**providers: Any) -> None:
    """Override providers, e.g. set_providers(llm=FakeLLM()). Used by tests."""
    _cache.update(providers)


def reset_providers() -> None:
    _cache.clear()
