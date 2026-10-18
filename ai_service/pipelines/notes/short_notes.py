"""Generate short revision notes for a topic. Owner: Samni.

Job type: GENERATE_SHORT_NOTES (dispatched by ai_service/routes/jobs.py)

Grounded with RAG: uses rag.retrieval.retriever + rag.context_builder,
never document_chunks directly.
"""

import uuid
from typing import Any

from ai_service.rag.context_builder import BuiltContext, build_context
from ai_service.rag.retrieval.retriever import retrieve
from shared.enums import SourceType

PROMPT_NAME = "notes/short_notes"
PROMPT_VERSION = 1


SOURCE_TYPES = [SourceType.APPROVED_NOTE, SourceType.SYLLABUS]


async def gather_context(query: str, topic_id: uuid.UUID | None = None, k: int = 6) -> BuiltContext:
    """Retrieve approved sources for the prompt (with citations)."""
    chunks = await retrieve(query, topic_id=topic_id, source_types=SOURCE_TYPES, k=k)
    return build_context(chunks)


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate short revision notes for a topic."""
    # TODO(Samni):
    #   1. same flow as generate_notes with the short_notes prompt
    return {"status": "todo", "pipeline": "notes.short_notes"}
