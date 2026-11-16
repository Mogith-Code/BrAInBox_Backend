"""Draft an AI answer to a student's question, grounded in approved notes.

Job type: SUGGEST_ANSWER (dispatched by ai_service/routes/jobs.py)

Payload: {"title": "...", "body": "...", "topic_id": "<uuid>" | null}
Result:  {"body": "markdown answer" | null, "citations": [...], "reason": "...",
          "prompt_version": "..."}

Grounded with RAG: uses rag.retrieval.retriever + rag.context_builder, never document_chunks
directly. When no approved source covers the question, NO answer is written (body = null):
a missing AI answer is better than an invented one. The post is data, never instructions.
"""

import logging
import uuid
from typing import Any

from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm
from ai_service.rag.context_builder import BuiltContext, build_context
from ai_service.rag.retrieval.retriever import retrieve
from shared.enums import SourceType

logger = logging.getLogger(__name__)

PROMPT_NAME = "community/suggested_answer"
PROMPT_VERSION = 1
PROMPT_ID = prompt_id(PROMPT_NAME, PROMPT_VERSION)
NO_ANSWER = "NO_ANSWER"  # what the model replies when the sources do not cover the question

SOURCE_TYPES = [SourceType.APPROVED_NOTE, SourceType.SYLLABUS, SourceType.TEACHER_GUIDE]


async def gather_context(query: str, topic_id: uuid.UUID | None = None, k: int = 6) -> BuiltContext:
    """Retrieve approved sources for the prompt (with citations): the post's topic first, then
    everything approved."""
    chunks = await retrieve(query, topic_id=topic_id, source_types=SOURCE_TYPES, k=k)
    if not chunks and topic_id is not None:
        chunks = await retrieve(query, source_types=SOURCE_TYPES, k=k)
    return build_context(chunks)


def _nothing(reason: str) -> dict[str, Any]:
    return {"body": None, "citations": [], "reason": reason, "prompt_version": PROMPT_ID}


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not (title or body):
        return _nothing("empty_post")
    topic_id = uuid.UUID(str(payload["topic_id"])) if payload.get("topic_id") else None
    try:
        context = await gather_context(f"{title}\n{body}"[:1000], topic_id)
    except Exception:
        logger.warning("Could not search the approved sources", exc_info=True)
        return _nothing("sources_unavailable")
    if not context.citations:
        return _nothing("no_sources")

    prompt = render_prompt(
        PROMPT_NAME, PROMPT_VERSION, title=title, body=body[:3000], context=context.text
    )
    answer = (await get_llm().generate(prompt, prompt_name=PROMPT_ID)).strip()
    if not answer or NO_ANSWER in answer:
        return _nothing("not_covered")
    return {
        "body": answer,
        "citations": [c.model_dump(mode="json") for c in context.citations],
        "reason": "ok",
        "prompt_version": PROMPT_ID,
        "model": getattr(get_llm(), "model", None) or getattr(get_llm(), "name", None),
    }
