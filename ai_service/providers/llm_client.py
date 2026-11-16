"""llm_client: the one LLM wrapper used by the Learn tab pipelines (notes + upload summaries).

    client = get_llm_client()
    text = await client.complete(prompt, task="notes_full", meta={"topic_title": "..."})

It returns the model's raw text; the pipeline parses and validates it (so it can repair bad
output and retry once). Provider, from the environment:

    LLM_PROVIDER=mock    deterministic, always-valid answers (no key, offline, tests)
    LLM_PROVIDER=gemini  the project's Gemini adapter (LLM_API_KEY / LLM_MODEL, or the GEMINI_*
                         values when those are empty), with its daily cap and usage logging
    (empty)              mock when the fakes are on (USE_FAKE_AI=true or no key), else gemini

`task` says what is asked for, so the mock can answer in the right format:
    notes_full | notes_short   -> a JSON list of blocks (shared/learn_blocks.py)
    summary_chunk              -> plain text (summary of one part of a long upload)
    upload_summary             -> JSON {"summary": "...", "key_points": [...]}
Tests inject their own client with `set_providers(llm_client=...)`.
"""

import json
import logging
from typing import Any, Protocol

from ai_service.config import get_settings

logger = logging.getLogger(__name__)

TASKS = ("notes_full", "notes_short", "summary_chunk", "upload_summary")


class LLMClient(Protocol):
    name: str

    async def complete(
        self,
        prompt: str,
        *,
        task: str,
        meta: dict[str, Any] | None = None,
        temperature: float | None = None,
        prompt_name: str | None = None,
    ) -> str: ...


class ProviderLLMClient:
    """Wraps an existing LLMProvider (e.g. GeminiLLM) from ai_service/providers."""

    def __init__(self, provider: Any):
        self._provider = provider
        self.name = getattr(provider, "name", "llm")

    async def complete(
        self,
        prompt: str,
        *,
        task: str,
        meta: dict[str, Any] | None = None,
        temperature: float | None = None,
        prompt_name: str | None = None,
    ) -> str:
        text: str = await self._provider.generate(
            prompt, temperature=temperature, prompt_name=prompt_name
        )
        return text


class MockLLMClient:
    """Deterministic answers that always pass validation. Uses `meta` for the topic title."""

    name = "mock-llm"

    async def complete(
        self,
        prompt: str,
        *,
        task: str,
        meta: dict[str, Any] | None = None,
        temperature: float | None = None,
        prompt_name: str | None = None,
    ) -> str:
        meta = meta or {}
        topic = meta.get("topic_title") or "this topic"
        if task == "notes_full":
            return json.dumps(mock_full_blocks(topic, meta))
        if task == "notes_short":
            return json.dumps(mock_short_blocks(topic))
        if task == "summary_chunk":
            words = prompt.split()
            return "Summary of this part: " + " ".join(words[-60:])
        if task == "upload_summary":
            return json.dumps(
                {
                    "summary": (
                        f"These notes explain the main ideas of {topic}. They define the key "
                        "terms, describe the processes step by step and link them to the "
                        "A/L Biology syllabus."
                    ),
                    "key_points": [f"Key idea {n} of {topic}" for n in range(1, 7)],
                }
            )
        raise ValueError(f"Unknown llm_client task: {task}")


def mock_full_blocks(topic: str, meta: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {"type": "heading", "text": f"1. {topic}: the main idea"},
        {
            "type": "paragraph",
            "text": f"{topic} is part of the A/L Biology syllabus. Learn the key terms first.",
            "highlights": ["key terms"],
        },
        {"type": "definition", "title": "Definition", "text": f"{topic} - a core concept."},
        {"type": "bullet_list", "items": ["First key point", "Second key point"]},
        {
            "type": "table",
            "caption": "Summary",
            "headers": ["Term", "Meaning"],
            "rows": [["Term A", "Meaning A"], ["Term B", "Meaning B"]],
        },
    ]
    if meta.get("include_examples", True):
        blocks.append({"type": "paragraph", "text": f"Example: a worked example on {topic}."})
    if meta.get("include_past_paper_tips", True):
        blocks.append(
            {"type": "tip", "title": "Past-paper tip", "text": "Define every term you use."}
        )
    return blocks


def mock_short_blocks(topic: str) -> list[dict[str, Any]]:
    return [
        {"type": "heading", "text": f"{topic}: short notes"},
        {"type": "bullet_list", "items": [f"{topic} point {n}" for n in range(1, 11)]},
    ]


def build_llm_client() -> LLMClient:
    s = get_settings()
    provider = (s.LLM_PROVIDER or ("mock" if s.use_fakes else "gemini")).strip().lower()
    if provider == "mock":
        return MockLLMClient()
    if provider == "gemini":
        from ai_service.providers.llm_gemini import GeminiLLM

        key = s.LLM_API_KEY or s.GEMINI_API_KEY
        if not key:
            logger.warning("LLM_PROVIDER=gemini but no LLM_API_KEY/GEMINI_API_KEY: using mock")
            return MockLLMClient()
        gemini = GeminiLLM(
            key, s.LLM_MODEL or s.GEMINI_MODEL, s.GEMINI_FALLBACK_MODEL, s.GEMINI_DAILY_LIMIT
        )
        return ProviderLLMClient(gemini)
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r} (use 'mock' or 'gemini')")
