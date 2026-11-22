"""Production settings: unsafe values stop the start-up with a clear message."""

import pytest
from pydantic import ValidationError

from ai_service.config import AISettings
from api.core.config import ApiSettings
from api.main import check_production_settings
from shared.settings import SharedSettings

SECRET = "x" * 40
# Everything a real production API needs (values are made up).
GOOD_API = {
    "ENVIRONMENT": "prod",
    "DATABASE_URL": "postgresql+asyncpg://u:p@db.example.org/brainbox?ssl=require",
    "AI_SERVICE_TOKEN": SECRET,
    "AUTH_CODE_SECRET": SECRET,
    "FIREBASE_PROJECT_ID": "brainbox-prod",
    "STORAGE_BUCKET": "brainbox-prod.firebasestorage.app",
    "EMAIL_BACKEND": "smtp",
    "SMTP_HOST": "smtp.example.org",
    "SMTP_USER": "sender",
    "SMTP_PASSWORD": "app-password",
    "CORS_ORIGINS": "https://admin.example.org",
    "AI_SERVICE_URL": "https://ai.example.org",
    "JOB_RUNNER": "cloudtasks",
    "JOBS_TARGET_URL": "https://api.example.org",
}


def api_settings(**changes: object) -> ApiSettings:
    # _env_file=None: ignore the developer's .env, use only these values.
    return ApiSettings(_env_file=None, **{**GOOD_API, **changes})  # type: ignore[arg-type]


def test_good_production_settings_pass():
    check_production_settings(api_settings())


@pytest.mark.parametrize("switch", ["DEV_LOGIN_ENABLED", "DEBUG_SHOW_ANSWERS", "DEV_EXPOSE_CODES"])
def test_dev_switches_cannot_be_turned_on_in_prod(switch):
    with pytest.raises(ValidationError, match=f"{switch} must be false when ENVIRONMENT=prod"):
        api_settings(**{switch: True})


def test_dev_switches_are_allowed_in_dev():
    settings = api_settings(ENVIRONMENT="dev", DEV_LOGIN_ENABLED=True, DEBUG_SHOW_ANSWERS=True)
    assert settings.DEV_LOGIN_ENABLED and settings.DEBUG_SHOW_ANSWERS


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"DATABASE_URL": SharedSettings.model_fields["DATABASE_URL"].default}, "DATABASE_URL"),
        ({"AI_SERVICE_TOKEN": "dev-service-token"}, "AI_SERVICE_TOKEN"),
        ({"AI_SERVICE_TOKEN": "short"}, "AI_SERVICE_TOKEN"),
        ({"AUTH_CODE_SECRET": "dev-only-change-me"}, "AUTH_CODE_SECRET"),
        ({"FIREBASE_PROJECT_ID": ""}, "FIREBASE_PROJECT_ID"),
        ({"STORAGE_BUCKET": ""}, "STORAGE_BUCKET"),
        ({"EMAIL_BACKEND": "console"}, "EMAIL_BACKEND"),
        ({"SMTP_PASSWORD": ""}, "SMTP_PASSWORD"),
        ({"CORS_ORIGINS": ""}, "CORS_ORIGINS"),
        ({"CORS_ORIGINS": "http://localhost:*,http://127.0.0.1:*"}, "exact https origins"),
        ({"CORS_ORIGINS": "https://*.example.org"}, "exact https origins"),
        ({"ADMIN_ORIGINS": "http://admin.example.org"}, "exact https origins"),
        ({"JOBS_TARGET_URL": ""}, "JOBS_TARGET_URL"),
        ({"JOB_RUNNER": "celery"}, "JOB_RUNNER"),
        ({"AI_SERVICE_URL": "http://localhost:8001"}, "AI_SERVICE_URL"),
    ],
)
def test_unsafe_production_settings_stop_the_start(changes, message):
    with pytest.raises(RuntimeError, match=message):
        check_production_settings(api_settings(**changes))


def test_all_problems_are_listed_at_once():
    settings = api_settings(AUTH_CODE_SECRET="dev-only-change-me", STORAGE_BUCKET="")
    with pytest.raises(RuntimeError) as error:
        check_production_settings(settings)
    assert "AUTH_CODE_SECRET" in str(error.value) and "STORAGE_BUCKET" in str(error.value)


@pytest.mark.parametrize(("value", "expected"), [("PROD", "prod"), ("production", "prod")])
def test_environment_names_are_normalised(value, expected):
    assert SharedSettings(_env_file=None, ENVIRONMENT=value).ENVIRONMENT == expected


def test_unknown_environment_is_refused():
    # A typo must not quietly run production with the dev defaults.
    with pytest.raises(ValidationError, match="ENVIRONMENT must be one of"):
        SharedSettings(_env_file=None, ENVIRONMENT="prdo")


def test_unknown_log_level_is_refused():
    with pytest.raises(ValidationError, match="LOG_LEVEL"):
        SharedSettings(_env_file=None, LOG_LEVEL="LOUD")


def test_ai_service_refuses_fake_ai_in_production():
    from ai_service.main import check_production_settings as check_ai

    good = {k: GOOD_API[k] for k in ("ENVIRONMENT", "DATABASE_URL", "AI_SERVICE_TOKEN")}
    good |= {k: GOOD_API[k] for k in ("FIREBASE_PROJECT_ID", "STORAGE_BUCKET")}
    check_ai(AISettings(_env_file=None, **good, USE_FAKE_AI=False, GEMINI_API_KEY="k"))
    with pytest.raises(RuntimeError, match="USE_FAKE_AI"):
        check_ai(AISettings(_env_file=None, **good, USE_FAKE_AI=True, GEMINI_API_KEY="k"))
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        check_ai(AISettings(_env_file=None, **good, USE_FAKE_AI=False, GEMINI_API_KEY=""))
    with pytest.raises(RuntimeError, match="LLM_PROVIDER"):
        check_ai(
            AISettings(
                _env_file=None, **good, USE_FAKE_AI=False, GEMINI_API_KEY="k", LLM_PROVIDER="mock"
            )
        )
