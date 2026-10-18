"""Generate A/L-style MCQs for a topic, grounded in the approved syllabus sources. Owner: Udith.

Ported from Udith's original `app/services/generator.py`:
  * retrieve syllabus context for the topic (RAG) - no context -> no questions
  * up to 3 existing questions are shown as style examples
  * the LLM output is validated (5 options, answer must be one of them); invalid output is
    retried MAX_RETRIES times
  * retries / fallback model for busy errors live in providers/llm_gemini.py

Job type: GENERATE_QUESTIONS (dispatched by ai_service/routes/jobs.py).
Also used by paper_builder.py (BUILD_PAPER).

Grounded with RAG: uses rag.retrieval.retriever + rag.context_builder,
never document_chunks directly.
"""

import uuid
from typing import Any

from pydantic import ValidationError

from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm
from ai_service.rag.context_builder import BuiltContext, build_context
from ai_service.rag.retrieval.retriever import retrieve
from ai_service.schemas.llm_outputs import GeneratedMCQ, GeneratedMCQSet
from shared.enums import SourceType

PROMPT_NAME = "questions/generate_mcq"
PROMPT_VERSION = 2
PROMPT_ID = prompt_id(PROMPT_NAME, PROMPT_VERSION)

SOURCE_TYPES = [SourceType.SYLLABUS, SourceType.TEACHER_GUIDE, SourceType.APPROVED_NOTE]
MAX_RETRIES = 2  # extra attempts when the LLM returns invalid questions
TEMPERATURE = 0.7  # a little creativity so questions differ between papers


class NoContextError(ValueError):
    """No approved source text was found for the topic, so we refuse to invent questions."""


async def gather_context(query: str, unit_id: uuid.UUID | None = None, k: int = 6) -> BuiltContext:
    """Search inside the topic's unit first; if that finds nothing, search all sources."""
    chunks = await retrieve(query, unit_id=unit_id, source_types=SOURCE_TYPES, k=k)
    if not chunks and unit_id is not None:
        chunks = await retrieve(query, source_types=SOURCE_TYPES, k=k)
    return build_context(chunks)


async def generate_for_topic(
    topic_title: str,
    count: int,
    *,
    unit_id: uuid.UUID | None = None,
    examples: list[dict[str, Any]] | None = None,
) -> tuple[list[GeneratedMCQ], BuiltContext]:
    """Return up to `count` validated MCQs and the context (with citations) they came from."""
    context = await gather_context(topic_title, unit_id)
    if not context.citations:
        raise NoContextError(f"No syllabus content found for topic '{topic_title}'")

    prompt = render_prompt(
        PROMPT_NAME,
        PROMPT_VERSION,
        topic_title=topic_title,
        count=count,
        context=context.text,
        examples=examples or [],
    )
    last_error: Exception | None = None
    for _ in range(MAX_RETRIES + 1):
        try:
            result = await get_llm().generate_json(
                prompt, GeneratedMCQSet, temperature=TEMPERATURE, prompt_name=PROMPT_ID
            )
            return result.questions[:count], context
        except ValidationError as exc:  # bad JSON or a question that breaks the rules
            last_error = exc
    raise RuntimeError(f"LLM output was invalid after retries: {last_error}")


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """GENERATE_QUESTIONS job.

    payload = {"topic_title": "Photosynthesis", "count": 5, "unit_id": "..."?, "examples": [...]?}
    """
    unit_id = uuid.UUID(payload["unit_id"]) if payload.get("unit_id") else None
    questions, context = await generate_for_topic(
        payload["topic_title"],
        int(payload.get("count", 5)),
        unit_id=unit_id,
        examples=payload.get("examples"),
    )
    return {
        "questions": [q.model_dump() for q in questions],
        "citations": [c.model_dump(mode="json") for c in context.citations],
        "prompt_version": PROMPT_ID,
    }
