"""Generate full notes for a topic. Owner: Samni.

Job type: GENERATE_NOTES (dispatched by ai_service/routes/jobs.py)

Grounded with RAG: uses rag.retrieval.retriever + rag.context_builder,
never document_chunks directly.
"""

import uuid
from typing import Any

from ai_service.rag.context_builder import BuiltContext, build_context
from ai_service.rag.retrieval.retriever import retrieve
from shared.enums import SourceType

PROMPT_NAME = "notes/generate_notes"
PROMPT_VERSION = 1


SOURCE_TYPES = [SourceType.SYLLABUS, SourceType.TEACHER_GUIDE, SourceType.APPROVED_NOTE]


async def gather_context(query: str, topic_id: uuid.UUID | None = None, k: int = 6) -> BuiltContext:
    """Retrieve approved sources for the prompt (with citations)."""
    chunks = await retrieve(query, topic_id=topic_id, source_types=SOURCE_TYPES, k=k)
    return build_context(chunks)


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate full notes for a topic."""
    # TODO(Samni):
    #   1. context = await gather_context(topic_title, topic_id)
    #   2. prompt = render_prompt(PROMPT_NAME, PROMPT_VERSION, unit_title=..., topic_title=..., context=context.text)
    #   3. notes = await get_llm().generate_json(prompt, GeneratedNotes)
    #   4. return notes + context.citations (the api stores them in notes.citations for admin review)
    return {"status": "todo", "pipeline": "notes.generate_notes"}
