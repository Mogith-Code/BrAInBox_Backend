"""Gemini LLM adapter (google-genai SDK).

Features: plain text generation, JSON generation validated against a Pydantic schema,
retry with exponential backoff + a fallback model, and token logging.

Retry rules (from Udith's original paper generator):
  * only "try again later" errors are retried: 429 (rate limit) and 500/503/504 (overloaded)
  * each round tries GEMINI_MODEL first, then GEMINI_FALLBACK_MODEL (if set)
  * waits 1s, 2s, 4s... between rounds; any other error (bad request, auth) fails at once

Free tier: every request is counted against GEMINI_DAILY_LIMIT (ai_service/daily_limits.py).
Still 429 after all retries = Google's own free limit -> DailyLimitReached (a clear message).
"""

import asyncio
import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel

from ai_service.config import get_settings
from ai_service.daily_limits import DailyLimitReached, use_quota

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

RETRYABLE_CODES = {429, 500, 503, 504}


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return getattr(exc, "code", None) in RETRYABLE_CODES


class GeminiLLM:
    name = "gemini"

    def __init__(self, api_key: str, model: str, fallback_model: str = "", daily_limit: int = 0):
        from google import genai  # imported here so the app starts without the SDK

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.models = [m for m in (model, fallback_model) if m]
        self.daily_limit = daily_limit  # 0 = no cap

    async def _call(self, prompt: str, config: Any, prompt_name: str | None) -> Any:
        settings = get_settings()
        last_error: Exception | None = None
        for attempt in range(settings.LLM_MAX_RETRIES):
            for model in self.models:
                # Raises DailyLimitReached (not retried) when today's free requests are used up.
                await use_quota(
                    "gemini", "generate", model, self.daily_limit, prompt_name=prompt_name
                )
                started = time.perf_counter()
                try:
                    response = await asyncio.wait_for(
                        self._client.aio.models.generate_content(
                            model=model, contents=prompt, config=config
                        ),
                        timeout=settings.LLM_TIMEOUT_SECONDS,
                    )
                    self._log_usage(model, response, prompt_name, started)
                    return response
                except Exception as exc:
                    if not _is_retryable(exc):
                        raise
                    last_error = exc
                    logger.warning("Gemini %s busy (attempt %s): %s", model, attempt + 1, exc)
            if attempt < settings.LLM_MAX_RETRIES - 1:
                await asyncio.sleep(2**attempt)
        if getattr(last_error, "code", None) == 429:  # Google's own (free-tier) limit
            raise DailyLimitReached(
                "The free AI limit is reached for now. Please try again later."
            ) from last_error
        raise RuntimeError(f"Gemini failed after retries: {last_error}") from last_error

    def _log_usage(
        self, model: str, response: Any, prompt_name: str | None, started: float
    ) -> None:
        usage = getattr(response, "usage_metadata", None)
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "gemini model=%s prompt=%s in_tokens=%s out_tokens=%s latency_ms=%s",
            model,
            prompt_name,
            getattr(usage, "prompt_token_count", None),
            getattr(usage, "candidates_token_count", None),
            latency_ms,
        )
        # TODO(Mogith): also insert a row into ai_usage_log (provider, model, tokens, latency).

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        prompt_name: str | None = None,
    ) -> str:
        from google.genai import types

        settings = get_settings()
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=settings.LLM_TEMPERATURE if temperature is None else temperature,
            max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        )
        response = await self._call(prompt, config, prompt_name)
        return str(response.text or "")

    async def generate_json(
        self,
        prompt: str,
        schema: type[SchemaT],
        *,
        system: str | None = None,
        temperature: float | None = None,
        prompt_name: str | None = None,
    ) -> SchemaT:
        from google.genai import types

        settings = get_settings()
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=settings.LLM_TEMPERATURE if temperature is None else temperature,
            max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
            response_schema=schema,
        )
        response = await self._call(prompt, config, prompt_name)
        # Validate ourselves so a bad answer fails loudly here (pydantic.ValidationError),
        # and the pipeline can decide to retry.
        return schema.model_validate_json(response.text or "{}")
