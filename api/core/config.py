"""Settings for the public API. Shared fields (DATABASE_URL, AI_SERVICE_TOKEN...)
come from `shared/settings.py`."""

import re
from functools import lru_cache

from shared.settings import SharedSettings


class ApiSettings(SharedSettings):
    # Where the internal AI service runs (docker compose overrides this to http://ai_service:8001)
    AI_SERVICE_URL: str = "http://localhost:8001"
    # Generating a whole paper calls the LLM once per topic, so allow a few minutes.
    AI_SERVICE_TIMEOUT_SECONDS: float = 180.0

    # Comma-separated list. "*" is allowed inside an entry, e.g. "http://localhost:*"
    CORS_ORIGINS: str = "http://localhost:*,http://127.0.0.1:*"

    # How AI jobs are run: "local" (FastAPI BackgroundTasks) or "cloudtasks" (Google Cloud Tasks)
    JOB_RUNNER: str = "local"

    YOUTUBE_API_KEY: str = ""

    # Dev only: include the correct answer in generated papers (ignored when ENVIRONMENT=prod).
    DEBUG_SHOW_ANSWERS: bool = False

    API_VERSION: str = "0.1.0"

    def cors_exact_origins(self) -> list[str]:
        """Origins without a wildcard, e.g. "https://admin.brainbox.lk"."""
        return [o for o in self._cors_list() if "*" not in o]

    def cors_origin_regex(self) -> str | None:
        """One regex for all wildcard origins, e.g. "http://localhost:*" -> any port."""
        patterns = []
        for origin in self._cors_list():
            if "*" in origin:
                # Escape everything, then turn "*" into "anything except '/'"
                patterns.append(re.escape(origin).replace(r"\*", r"[^/]*"))
        return "^(" + "|".join(patterns) + ")$" if patterns else None

    def _cors_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> ApiSettings:
    return ApiSettings()
