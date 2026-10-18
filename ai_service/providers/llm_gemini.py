"""Gemini LLM adapter (google-genai SDK).

Features: plain text generation, JSON generation validated against a Pydantic schema,
simple retry with exponential backoff, and token logging.
"""

import asyncio
import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel

from ai_service.config import get_settings

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class GeminiLLM:
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        from google import genai  # imported here so the app starts without the SDK

        self._client = genai.Client(api_key=api_key)
        self.model = model

    async def _call(self, prompt: str, config: Any, prompt_name: str | None) -> Any:
        settings = get_settings()
        last_error: Exception | None = None
        for attempt in range(1, settings.LLM_MAX_RETRIES + 1):
            started = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=self.model, contents=prompt, config=config
                    ),
                    timeout=settings.LLM_TIMEOUT_SECONDS,
                )
                self._log_usage(response, prompt_name, started)
                return response
            except Exception as exc:
                last_error = exc
                wait = 2**attempt
                logger.warning(
                    "Gemini call failed (attempt %s/%s): %s - retrying in %ss",
                    attempt,
                    settings.LLM_MAX_RETRIES,
                    exc,
                    wait,
                )
                if attempt < settings.LLM_MAX_RETRIES:
                    await asyncio.sleep(wait)
        raise RuntimeError(f"Gemini failed after retries: {last_error}") from last_error

    def _log_usage(self, response: Any, prompt_name: str | None, started: float) -> None:
        usage = getattr(response, "usage_metadata", None)
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "gemini model=%s prompt=%s in_tokens=%s out_tokens=%s latency_ms=%s",
            self.model,
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
        prompt_name: str | None = None,
    ) -> SchemaT:
        from google.genai import types

        settings = get_settings()
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=settings.LLM_TEMPERATURE,
            max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
            response_schema=schema,
        )
        response = await self._call(prompt, config, prompt_name)
        # Validate ourselves so a bad answer fails loudly here, not later in the pipeline.
        return schema.model_validate_json(response.text or "{}")
