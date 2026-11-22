"""Ask BrAInBox: answer a student's question from the approved books only.

Called through POST /sync/ask-tutor. Flow:
    1. find the closest passages (inside the topic's unit first)
    2. ask the AI to answer from those passages only
    3. no passages, or the AI says they don't contain the answer -> an honest "not found"
"""

import uuid
from typing import Any

from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm
from ai_service.rag.context_builder import build_context
from ai_service.rag.retrieval.retriever import retrieve
from ai_service.schemas.llm_outputs import TutorAnswer
from shared.enums import SourceType

PROMPT_NAME = "notes/ask_tutor"
PROMPT_VERSION = 1
SOURCE_TYPES = [SourceType.SYLLABUS, SourceType.TEACHER_GUIDE, SourceType.APPROVED_NOTE]
TEMPERATURE = 0.2  # stay close to the source text
NOT_FOUND = (
    "I couldn't find this in the approved Biology notes. "
    "Try asking in a different way, or ask your teacher."
)


def _not_found() -> dict[str, Any]:
    return {"answer": NOT_FOUND, "grounded": False, "sources": []}


async def ask(
    question: str, *, topic_title: str = "", unit_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """{"answer": str, "grounded": bool, "sources": [{"title", "page"}]}"""
    query = f"{topic_title}: {question}" if topic_title else question
    chunks = await retrieve(query, unit_id=unit_id, source_types=SOURCE_TYPES, k=6)
    if not chunks and unit_id is not None:
        chunks = await retrieve(query, source_types=SOURCE_TYPES, k=6)
    context = build_context(chunks)
    if not context.citations:
        return _not_found()

    prompt = render_prompt(
        PROMPT_NAME,
        PROMPT_VERSION,
        topic_title=topic_title,
        question=question,
        context=context.text,
    )
    result = await get_llm().generate_json(
        prompt,
        TutorAnswer,
        temperature=TEMPERATURE,
        prompt_name=prompt_id(PROMPT_NAME, PROMPT_VERSION),
    )
    used = [c for c in context.citations if c.ref in result.used_sources]
    if not result.found_in_sources or not used:
        return _not_found()

    sources: list[dict[str, Any]] = []
    for citation in used:
        source = {"title": citation.document_title, "page": citation.page}
        if source not in sources:
            sources.append(source)
    return {"answer": result.answer.strip(), "grounded": True, "sources": sources}
