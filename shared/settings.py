"""Settings shared by the api and the ai_service.

Values come from environment variables (or a local `.env` file).
See `.env.example` for every variable with a comment.
Each service extends `SharedSettings` with its own fields
(`api/core/config.py` and `ai_service/config.py`).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class SharedSettings(BaseSettings):
    # Read from the environment first, then from `.env`. Unknown variables are ignored,
    # so both services can share one `.env` file.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "dev", "test" or "prod"
    ENVIRONMENT: str = "dev"
    LOG_LEVEL: str = "INFO"

    # Async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@host:5432/dbname
    DATABASE_URL: str = "postgresql+asyncpg://brainbox:brainbox@localhost:5432/brainbox"

    # Secret shared by api and ai_service. The api sends it in the X-Service-Token header.
    AI_SERVICE_TOKEN: str = "dev-service-token"

    # Use the deterministic fake AI providers (no API keys needed).
    USE_FAKE_AI: bool = True

    # Firebase / Google Cloud
    FIREBASE_PROJECT_ID: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    STORAGE_BUCKET: str = ""
    # Dev only: when STORAGE_BUCKET is empty, uploads are kept in this folder instead.
    # The api writes and the ai_service reads it, so both must see the same folder
    # (they do when run from the repo root, and in docker compose through the `.:/app` mount).
    LOCAL_STORAGE_DIR: str = "data/local_storage"

    # Public URL of the logo (used in docs, emails, notifications)
    LOGO_URL: str = "/static/brand/logo_horizontal_1200.png"


@lru_cache
def get_shared_settings() -> SharedSettings:
    """Return one cached settings object (read the environment only once)."""
    return SharedSettings()
