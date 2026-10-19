"""Topic-based summary: summarise a topic from the student's notes, or from approved sources.
Owner: Samni. Jira: SCRUM-37.

Two ways to call it:
  * with notes   -> the student's own text (pasted notes, or the text of an upload) is summarised
  * topic only   -> no notes given, so approved sources for the topic are found with RAG and
                    summarised (with [n] citations). No sources -> NoContextError, never invented.

Long notes use map-reduce:
  1. map:    split into parts and summarise each part (summarize_chunk prompt, plain text)
  2. reduce: merge the part summaries into one TopicSummary (summarize_topic prompt, JSON)
Short notes skip the map step.

Job type: SUMMARIZE_UPLOAD (dispatched by ai_service/routes/jobs.py)
"""

import uuid
from typing import Any

from pydantic import ValidationError

from ai_service.pipelines.summarization.chunker import split_for_summary
from ai_service.pipelines.summarization.preprocess import preprocess
from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm
from ai_service.rag.context_builder import BuiltContext, build_context
from ai_service.rag.retrieval.retriever import retrieve
from ai_service.schemas.llm_outputs import TopicSummary
from shared.enums import SourceType

CHUNK_PROMPT_NAME = "summarization/summarize_chunk"
CHUNK_PROMPT_VERSION = 1
PROMPT_NAME = "summarization/summarize_topic"
PROMPT_VERSION = 1
PROMPT_ID = prompt_id(PROMPT_NAME, PROMPT_VERSION)  # stored in summaries.prompt_version

SOURCE_TYPES = [SourceType.SYLLABUS, SourceType.TEACHER_GUIDE, SourceType.APPROVED_NOTE]
MAX_PART_WORDS = 1500  # notes longer than this are summarised part by part
MAX_RETRIES = 2  # extra attempts when the LLM returns invalid JSON
TEMPERATURE = 0.3  # low: a summary should stick to the text


class NoContextError(ValueError):
    """No notes were given and no approved sources exist for the topic."""


async def gather_context(
    topic_title: str, topic_id: uuid.UUID | None = None, k: int = 6
) -> BuiltContext:
    """Search approved sources for the topic. Same pattern as notes/generate_notes.py."""
    chunks = await retrieve(topic_title, topic_id=topic_id, source_types=SOURCE_TYPES, k=k)
    return build_context(chunks)


async def summarize_parts(parts: list[str]) -> str:
    """Map step: summarise each part on its own and join the results."""
    llm = get_llm()
    part_summaries = []
    for number, part in enumerate(parts, start=1):
        prompt = render_prompt(
            CHUNK_PROMPT_NAME,
            CHUNK_PROMPT_VERSION,
            chunk_text=part,
            chunk_number=number,
            total_chunks=len(parts),
        )
        summary = await llm.generate(
            prompt,
            temperature=TEMPERATURE,
            prompt_name=prompt_id(CHUNK_PROMPT_NAME, CHUNK_PROMPT_VERSION),
        )
        part_summaries.append(f"Part {number}:\n{summary}")
    return "\n\n".join(part_summaries)


async def summarize_topic(
    topic_title: str,
    source_text: str,
    *,
    unit_title: str = "",
    from_parts: bool = False,
    grounded: bool = False,
) -> TopicSummary:
    """Reduce step: ask the LLM for the final summary as validated JSON."""
    prompt = render_prompt(
        PROMPT_NAME,
        PROMPT_VERSION,
        topic_title=topic_title,
        unit_title=unit_title,
        source_text=source_text,
        from_parts=from_parts,
        grounded=grounded,
    )
    last_error: Exception | None = None
    for _ in range(MAX_RETRIES + 1):
        try:
            return await get_llm().generate_json(
                prompt, TopicSummary, temperature=TEMPERATURE, prompt_name=PROMPT_ID
            )
        except ValidationError as exc:  # bad JSON or missing fields
            last_error = exc
    raise RuntimeError(f"LLM output was invalid after retries: {last_error}")


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """SUMMARIZE_UPLOAD job.

    payload = {
        "topic_title": "Osmosis",   # required
        "text": "...",              # optional: the student's notes
        "topic_id": "...",          # optional: narrows the RAG search, saved on the summary
        "unit_title": "Unit 2",     # optional: extra context for the prompt
    }
    """
    topic_title = (payload.get("topic_title") or "").strip()
    if not topic_title:
        raise ValueError("topic_title is required")
    topic_id = uuid.UUID(payload["topic_id"]) if payload.get("topic_id") else None
    unit_title = payload.get("unit_title") or ""
    citations: list[dict[str, Any]] = []

    if payload.get("text"):
        # 1. Summarise the student's own notes.
        source = "notes"
        parts = split_for_summary(preprocess(payload["text"]), max_words=MAX_PART_WORDS)
        from_parts = len(parts) > 1
        source_text = await summarize_parts(parts) if from_parts else parts[0]
        summary = await summarize_topic(
            topic_title, source_text, unit_title=unit_title, from_parts=from_parts
        )
    else:
        # 2. No notes: summarise the approved sources for the topic (grounded with RAG).
        source = "rag"
        context = await gather_context(topic_title, topic_id)
        if not context.citations:
            raise NoContextError(f"No notes given and no sources found for topic '{topic_title}'")
        summary = await summarize_topic(
            topic_title, context.text, unit_title=unit_title, grounded=True
        )
        citations = [c.model_dump(mode="json") for c in context.citations]

    return {
        **summary.model_dump(),
        "topic_id": str(topic_id) if topic_id else None,
        "source": source,
        "citations": citations,
        "prompt_version": PROMPT_ID,
    }
