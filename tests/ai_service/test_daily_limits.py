"""Tests for the free-tier daily caps (ai_service/daily_limits.py) and what happens when one
is reached. Owner: Mogith.

Tests marked @pytest.mark.db count rows in ai_usage_log, so they need PostgreSQL.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete

from ai_service import daily_limits
from ai_service.config import get_settings
from ai_service.daily_limits import DailyLimitReached, day_start, has_quota, use_quota
from ai_service.pipelines.visuals import decide_visual
from ai_service.providers import (
    can_draw_illustrations,
    get_image_generator,
    llm_gemini,
    reset_providers,
    set_providers,
)
from ai_service.providers.fakes import FakeImageGenerator
from ai_service.providers.image_gen import CloudflareImageGenerator
from ai_service.providers.llm_gemini import GeminiLLM
from ai_service.rag.context_builder import BuiltContext
from ai_service.schemas.llm_outputs import VisualDecision
from shared.db.models import AIUsageLog
from tests.ai_service.test_visuals_pipeline import FLOWCHART, ScriptedLLM, decision, payload


@pytest.fixture(autouse=True)
def no_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty(query, topic_id):  # type: ignore[no-untyped-def]
        return BuiltContext(text="", citations=[])

    monkeypatch.setattr(decide_visual, "gather_context", empty)


@pytest.fixture
async def provider(db_session):  # type: ignore[no-untyped-def]
    """A provider name used only by this test; its usage rows are removed afterwards."""
    name = f"test-{uuid.uuid4().hex[:8]}"
    yield name
    await db_session.execute(delete(AIUsageLog).where(AIUsageLog.provider == name))
    await db_session.commit()


def broken_database():  # type: ignore[no-untyped-def]
    raise ConnectionError("database down")


# --------------------------------------------------------------------------- the counter


def test_day_starts_follow_each_provider() -> None:
    now = datetime(2026, 11, 1, 5, 0, tzinfo=UTC)
    # Cloudflare resets at 00:00 UTC
    assert day_start("cloudflare", now) == datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    # Google resets at midnight Pacific (we use UTC-8): 05:00 UTC is still 31 Oct there
    assert day_start("gemini", now) == datetime(2026, 10, 31, 8, 0, tzinfo=UTC)


async def test_no_cap_never_touches_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daily_limits, "SessionLocal", broken_database)
    await use_quota("gemini", "generate", "gemini-2.5-flash", 0)  # no error
    assert await has_quota("gemini", "generate", 0) is True


async def test_database_down_lets_the_call_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daily_limits, "SessionLocal", broken_database)
    await use_quota("gemini", "generate", "gemini-2.5-flash", 5)  # logged, not raised
    assert await has_quota("gemini", "generate", 5) is True


@pytest.mark.db
async def test_cap_stops_calls_after_the_limit(provider: str) -> None:
    await use_quota(provider, "image", "flux", 2, images=1)
    await use_quota(provider, "image", "flux", 2, images=1)
    assert await has_quota(provider, "image", 2) is False
    with pytest.raises(DailyLimitReached) as caught:
        await use_quota(provider, "image", "flux", 2, images=1)
    assert caught.value.code == "AI_DAILY_LIMIT"
    assert "pictures" in caught.value.message
    # Other operations of the same provider have their own count
    assert await has_quota(provider, "generate", 2) is True


# --------------------------------------------------------------------------- providers


async def test_gemini_stops_before_calling_google(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def generate_content(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs["model"])

    async def no_quota(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise DailyLimitReached(daily_limits.limit_message("generate"))

    monkeypatch.setattr(llm_gemini, "use_quota", no_quota)
    llm = fake_gemini(generate_content)
    with pytest.raises(DailyLimitReached):
        await llm.generate("hello")
    assert calls == []  # Google was never called


async def test_google_429_becomes_a_clear_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class QuotaExhausted(Exception):
        code = 429

    async def generate_content(**kwargs):  # type: ignore[no-untyped-def]
        raise QuotaExhausted("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(get_settings(), "LLM_MAX_RETRIES", 1)
    with pytest.raises(DailyLimitReached, match="free AI limit"):
        await fake_gemini(generate_content).generate("hello")


def fake_gemini(generate_content: Any) -> GeminiLLM:
    """A GeminiLLM whose SDK client is replaced (no key, no network), with no daily cap."""
    llm = GeminiLLM.__new__(GeminiLLM)
    llm.model = "gemini-2.5-flash"
    llm.models = ["gemini-2.5-flash"]
    llm.daily_limit = 0
    llm._client = SimpleNamespace(  # type: ignore[attr-defined]
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    )
    return llm


async def test_illustrations_need_a_real_image_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    # Tests / offline dev: the fake picture is fine
    assert await can_draw_illustrations() is True

    # Real AI on, but no Cloudflare key: no pictures (we never show the fake to students)
    monkeypatch.setattr(settings, "USE_FAKE_AI", False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "a-key")
    monkeypatch.setattr(settings, "IMAGE_PROVIDER", "cloudflare")
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "")
    reset_providers()
    assert isinstance(get_image_generator(), FakeImageGenerator)
    assert await can_draw_illustrations() is False

    # A real provider with free pictures left (no cap here, so no database needed)
    monkeypatch.setattr(settings, "IMAGE_DAILY_LIMIT", 0)
    set_providers(image=CloudflareImageGenerator("acc", "tok", "flux"))
    assert await can_draw_illustrations() is True


def test_free_provider_is_the_default() -> None:
    settings = get_settings()
    assert settings.IMAGE_PROVIDER == "cloudflare"
    assert settings.IMAGE_DAILY_LIMIT > 0 and settings.GEMINI_DAILY_LIMIT > 0


# --------------------------------------------------------------------------- visuals fallback


async def test_no_free_pictures_means_a_diagram(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_pictures() -> bool:
        return False

    monkeypatch.setattr(decide_visual, "can_draw_illustrations", no_pictures)
    illustration = decision(kind="illustration", mermaid_code=None, image_prompt="A plant cell")
    llm = ScriptedLLM(illustration, decision(kind="diagram", mermaid_code=FLOWCHART))
    set_providers(llm=llm)

    result = await decide_visual.run(payload(visual_type="structure"))
    assert result["kind"] == "diagram"
    assert result["mermaid_code"] == FLOWCHART
    assert "Pictures are not available right now" in llm.prompts[0]
    assert len(llm.prompts) == 2  # the illustration answer was refused and asked again


async def test_last_free_picture_taken_falls_back_to_a_diagram() -> None:
    class LimitReachedImages(FakeImageGenerator):
        async def generate_image(self, prompt: str) -> bytes:
            raise DailyLimitReached(daily_limits.limit_message("image"))

    illustration = decision(kind="illustration", mermaid_code=None, image_prompt="A plant cell")
    llm = ScriptedLLM(illustration, decision(kind="flowchart", mermaid_code=FLOWCHART))
    set_providers(llm=llm, image=LimitReachedImages())

    result = await decide_visual.run(payload(visual_type="structure"))
    assert result["kind"] == "flowchart"
    assert result["mermaid_code"] == FLOWCHART
    assert all(label["x"] is None for label in result["labels"])
    assert "Pictures are not available right now" in llm.prompts[1]


def test_fake_example_is_still_a_valid_decision() -> None:
    assert VisualDecision.model_validate(VisualDecision.fake_example()).is_biology
