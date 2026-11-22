"""Settings for the public API. Shared fields (DATABASE_URL, AI_SERVICE_TOKEN...)
come from `shared/settings.py`."""

import re
from datetime import date
from functools import lru_cache

from pydantic import model_validator

from shared.settings import SharedSettings

DEFAULT_AUTH_CODE_SECRET = "dev-only-change-me"
# Switches that help on a laptop and are dangerous on a real server.
DEV_ONLY_SWITCHES = ("DEV_LOGIN_ENABLED", "DEBUG_SHOW_ANSWERS", "DEV_EXPOSE_CODES")


class ApiSettings(SharedSettings):
    # Where the internal AI service runs (docker compose overrides this to http://ai_service:8001)
    AI_SERVICE_URL: str = "http://localhost:8001"
    # Generating a whole paper calls the LLM once per topic, so allow a few minutes.
    AI_SERVICE_TIMEOUT_SECONDS: float = 180.0
    # Production only: the ai_service's own https URL. When set, calls also carry a Google
    # identity token for it, so the ai_service can be a private Cloud Run service.
    AI_SERVICE_AUDIENCE: str = ""

    # Browser origins allowed to call the API (the admin portal; the mobile app needs none).
    # Comma-separated. "*" is allowed inside an entry in dev only, e.g. "http://localhost:*".
    # Production: exact https origins only, e.g. "https://admin.brainbox.lk".
    CORS_ORIGINS: str = "http://localhost:*,http://127.0.0.1:*"
    # Extra origins for the deployed admin portal, e.g. "https://admin.brainbox.lk" (comma-separated)
    ADMIN_ORIGINS: str = ""

    # --- Request rate limits per minute (api/core/rate_limit.py). 0 = off.
    # Auth: per client IP on the sign-up / email-code / password-reset routes.
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10
    # AI: per logged-in user on the routes that start AI work (notes, papers, evaluations...).
    RATE_LIMIT_AI_PER_MINUTE: int = 20
    # How many proxies in front of the API append to X-Forwarded-For. Cloud Run = 1.
    # The client IP is the entry that many places from the right. 0 = use the socket address.
    RATE_LIMIT_PROXY_HOPS: int = 1

    # How AI jobs are run: "local" (FastAPI BackgroundTasks) or "cloudtasks" (Google Cloud Tasks)
    JOB_RUNNER: str = "local"
    # --- JOB_RUNNER=cloudtasks (production on Cloud Run)
    CLOUD_TASKS_PROJECT: str = ""  # empty = FIREBASE_PROJECT_ID
    CLOUD_TASKS_LOCATION: str = "asia-south1"
    CLOUD_TASKS_QUEUE: str = "brainbox-jobs"
    # Public https URL of THIS api service; the queue calls /api/v1/internal/jobs/{id}/run on it.
    JOBS_TARGET_URL: str = ""
    # Service account the queue signs its calls with (optional, adds an OIDC token).
    CLOUD_TASKS_SERVICE_ACCOUNT: str = ""
    CLOUD_TASKS_DEADLINE_SECONDS: int = 600

    # --- Daily limits per student for the AI-heavy endpoints (0 = no limit)
    EVALUATIONS_DAILY_LIMIT: int = 30
    OCR_DAILY_LIMIT_PER_USER: int = 10
    PAPERS_DAILY_LIMIT: int = 5
    COMMUNITY_POSTS_DAILY_LIMIT: int = 20
    # Photos of handwritten answers: at most this many pages, each at most this big.
    ANSWER_MAX_PAGES: int = 6
    ANSWER_IMAGE_MAX_MB: int = 8

    YOUTUBE_API_KEY: str = ""

    # Dev only: include the correct answer in generated papers (ignored when ENVIRONMENT=prod).
    DEBUG_SHOW_ANSWERS: bool = False

    # --- 6-digit email codes (verify email + password reset)
    # Secret mixed into the code / reset-token hashes. MUST be a long random value outside dev.
    AUTH_CODE_SECRET: str = DEFAULT_AUTH_CODE_SECRET
    # Dev only: return the code in the API response ("dev_code") so you can test without email.
    # Works ONLY when ENVIRONMENT=dev; ignored everywhere else.
    DEV_EXPOSE_CODES: bool = False
    # Dev only: accept "Bearer dev-token" (test student) / "Bearer dev-admin" (test admin) in /docs,
    # for requests from this computer, so you can test without Firebase. ENVIRONMENT must be dev:
    # the api refuses to start with this on anywhere else (api/main.py).
    DEV_LOGIN_ENABLED: bool = False

    # --- Email sending: "console" (prints to the log, dev) or "smtp"
    EMAIL_BACKEND: str = "console"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True  # STARTTLS on port 587
    SMTP_USE_SSL: bool = False  # SSL from the start (port 465 turns this on automatically)
    SMTP_TIMEOUT_SECONDS: float = 15.0
    EMAIL_FROM: str = "BrAInBox <no-reply@example.com>"

    # --- A/L exam dates per year, JSON in the env, e.g. {"2027": "2027-08-02"} (real dates TBD)
    AL_EXAM_DATES: dict[int, date] = {}

    # --- Visuals
    # How many visuals one student may ask for in 24 hours (each one costs an AI call).
    VISUALS_DAILY_LIMIT: int = 20
    # Signed image URLs (Firebase Storage) stay valid this long. 7 days is the maximum.
    VISUAL_URL_EXPIRY_DAYS: int = 7
    # Dev only (no STORAGE_BUCKET): image URLs point at this API, e.g. http://10.0.2.2:8000.
    # Empty = the address the app used for the request (works for the emulator and localhost).
    PUBLIC_BASE_URL: str = ""

    API_VERSION: str = "0.1.0"

    @model_validator(mode="after")
    def _no_dev_switches_in_prod(self) -> "ApiSettings":
        """Make the dev-only switches impossible to turn on in production."""
        if self.ENVIRONMENT == "prod":
            on = [name for name in DEV_ONLY_SWITCHES if getattr(self, name)]
            if on:
                raise ValueError(f"{', '.join(on)} must be false when ENVIRONMENT=prod")
        return self

    def production_problems(self) -> list[str]:
        """Every setting that is unsafe or missing for production (empty list = all good)."""
        problems = self.shared_production_problems()
        if len(self.AUTH_CODE_SECRET) < 32 or self.AUTH_CODE_SECRET == DEFAULT_AUTH_CODE_SECRET:
            problems.append("AUTH_CODE_SECRET must be a random secret of 32+ characters")
        if self.EMAIL_BACKEND != "smtp":
            problems.append("EMAIL_BACKEND must be smtp (console would not send the codes)")
        elif not (self.SMTP_HOST and self.SMTP_USER and self.SMTP_PASSWORD):
            problems.append(
                "SMTP_HOST, SMTP_USER and SMTP_PASSWORD are needed with EMAIL_BACKEND=smtp"
            )
        on = [name for name in DEV_ONLY_SWITCHES if getattr(self, name)]
        if on:
            problems.append(f"{', '.join(on)} must be false")
        origins = self._cors_list()
        if not origins:
            problems.append("CORS_ORIGINS / ADMIN_ORIGINS must list the admin portal origin(s)")
        bad = [o for o in origins if "*" in o or not o.startswith("https://")]
        if bad:
            problems.append(
                "CORS_ORIGINS / ADMIN_ORIGINS allow only exact https origins in production, "
                f"not {', '.join(bad)}"
            )
        if self.JOB_RUNNER not in ("local", "cloudtasks"):
            problems.append("JOB_RUNNER must be local or cloudtasks")
        if self.JOB_RUNNER == "cloudtasks" and not self.JOBS_TARGET_URL:
            problems.append("JOBS_TARGET_URL is needed with JOB_RUNNER=cloudtasks")
        if any(host in self.AI_SERVICE_URL for host in ("localhost", "127.0.0.1")):
            problems.append("AI_SERVICE_URL still points at this computer (localhost)")
        return problems

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
        origins = f"{self.CORS_ORIGINS},{self.ADMIN_ORIGINS}"
        return [o.strip() for o in origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> ApiSettings:
    return ApiSettings()
