"""Settings shared by the api and the ai_service.

Values come from environment variables (or a local `.env` file).
See `.env.example` for every variable with a comment.
Each service extends `SharedSettings` with its own fields
(`api/core/config.py` and `ai_service/config.py`).
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Every value the code checks. Anything else is refused at start-up: a typo such as
# "production" would otherwise skip every production safety check.
ENVIRONMENTS = {"dev", "test", "prod"}
_ENVIRONMENT_ALIASES = {"development": "dev", "production": "prod"}
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
# The built-in DATABASE_URL (a local docker database). Production must set its own.
DEFAULT_DATABASE_URL = "postgresql+asyncpg://brainbox:brainbox@localhost:5432/brainbox"
DEFAULT_SERVICE_TOKEN = "dev-service-token"


class SharedSettings(BaseSettings):
    # Read from the environment first, then from `.env`. Unknown variables are ignored,
    # so both services can share one `.env` file.
    # hide_input_in_errors: a refused setting must not print the other values (secrets) to the log.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    # "dev", "test" or "prod"
    ENVIRONMENT: str = "dev"
    LOG_LEVEL: str = "INFO"

    # Async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@host:5432/dbname
    DATABASE_URL: str = DEFAULT_DATABASE_URL

    # Secret shared by api and ai_service. The api sends it in the X-Service-Token header.
    AI_SERVICE_TOKEN: str = DEFAULT_SERVICE_TOKEN

    # Use the deterministic fake AI providers (no API keys needed).
    USE_FAKE_AI: bool = True

    # Firebase / Google Cloud
    FIREBASE_PROJECT_ID: str = ""
    # Firebase Web API key (public; from Project settings > Your apps). Only test scripts use it.
    FIREBASE_WEB_API_KEY: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    STORAGE_BUCKET: str = ""
    # Dev only: when STORAGE_BUCKET is empty, uploads are kept in this folder instead.
    # The api writes and the ai_service reads it, so both must see the same folder
    # (they do when run from the repo root, and in docker compose through the `.:/app` mount).
    LOCAL_STORAGE_DIR: str = "data/local_storage"

    # --- Learn tab uploads (POST /api/v1/learn/uploads). Without STORAGE_BUCKET the files are
    # kept in UPLOAD_DIR (the api writes, the ai_service reads). With a bucket they go to
    # Storage under uploads/learn/. Files larger than MAX_UPLOAD_MB are refused (413).
    UPLOAD_DIR: str = "data/local_storage/learn_uploads"
    MAX_UPLOAD_MB: int = 10

    # Public URL of the logo (used in docs, emails, notifications)
    LOGO_URL: str = "/static/brand/logo_horizontal_1200.png"

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def _check_environment(cls, value: object) -> str:
        name = str(value).strip().lower()
        name = _ENVIRONMENT_ALIASES.get(name, name)
        if name not in ENVIRONMENTS:
            raise ValueError(f"ENVIRONMENT must be one of dev, test, prod (got {value!r})")
        return name

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _check_log_level(cls, value: object) -> str:
        level = str(value).strip().upper()
        if level not in LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {', '.join(sorted(LOG_LEVELS))}")
        return level

    def shared_production_problems(self) -> list[str]:
        """Settings both services need in production (empty list = all good)."""
        problems = []
        if self.DATABASE_URL == DEFAULT_DATABASE_URL:
            problems.append("DATABASE_URL must point at the production database")
        if len(self.AI_SERVICE_TOKEN) < 32 or self.AI_SERVICE_TOKEN == DEFAULT_SERVICE_TOKEN:
            problems.append("AI_SERVICE_TOKEN must be a random secret of 32+ characters")
        if not self.FIREBASE_PROJECT_ID:
            problems.append("FIREBASE_PROJECT_ID is empty (logins cannot be checked)")
        if not self.STORAGE_BUCKET:
            problems.append("STORAGE_BUCKET is empty (uploads have nowhere to go)")
        return problems


@lru_cache
def get_shared_settings() -> SharedSettings:
    """Return one cached settings object (read the environment only once)."""
    return SharedSettings()
