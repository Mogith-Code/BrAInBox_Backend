"""Settings for the AI service. Shared fields come from `shared/settings.py`."""

from functools import lru_cache

from shared.settings import SharedSettings


class AISettings(SharedSettings):
    # --- Gemini (LLM + embeddings + images)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    # Tried when GEMINI_MODEL is overloaded / rate limited (429, 5xx). Empty = no fallback.
    GEMINI_FALLBACK_MODEL: str = ""
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"
    EMBEDDING_DIM: int = 768  # must match vector(768) in the database

    # --- Images (visuals module)
    # Who draws illustrations: "gemini" (IMAGE_MODEL below) or "cloudflare" (Workers AI FLUX).
    IMAGE_PROVIDER: str = "gemini"
    # gemini-2.5-flash-image ("Nano Banana") uses generate_content. "imagen-*" models still work.
    IMAGE_MODEL: str = "gemini-2.5-flash-image"
    CLOUDFLARE_ACCOUNT_ID: str = ""
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_IMAGE_MODEL: str = "@cf/black-forest-labs/flux-1-schnell"
    IMAGE_TIMEOUT_SECONDS: float = 60.0
    # Kroki turns Mermaid text into a PNG (free, open source, can be self-hosted with Docker).
    KROKI_URL: str = "https://kroki.io"
    KROKI_TIMEOUT_SECONDS: float = 15.0

    # --- OCR (Google Cloud Vision, uses GOOGLE_APPLICATION_CREDENTIALS)
    OCR_LANGUAGE_HINTS: str = "en"
    # Local OCR (Tesseract) for scanned PDF pages during RAG ingestion. Empty = find it on PATH.
    # Windows example: C:\Program Files\Tesseract-OCR\tesseract.exe
    TESSERACT_CMD: str = ""

    # --- Limits
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_OUTPUT_TOKENS: int = 4096
    LLM_MAX_RETRIES: int = 3
    LLM_TIMEOUT_SECONDS: float = 60.0
    MAX_INPUT_CHARS: int = 60_000
    EMBEDDING_BATCH_SIZE: int = 100

    # --- RAG
    RAG_CHUNK_TOKENS: int = 500
    RAG_CHUNK_OVERLAP: int = 50
    RAG_TOP_K: int = 8
    RAG_VECTOR_WEIGHT: float = 0.6  # 0.6 * vector score + 0.4 * keyword score

    API_VERSION: str = "0.1.0"

    @property
    def use_fakes(self) -> bool:
        """Fake providers are used when asked for, or when no Gemini key is set."""
        return self.USE_FAKE_AI or not self.GEMINI_API_KEY


@lru_cache
def get_settings() -> AISettings:
    return AISettings()
