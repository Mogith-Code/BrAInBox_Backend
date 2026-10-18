"""Draft an AI answer to a student question (RAG-grounded). Owner: Mogith.

Job type: SUGGEST_ANSWER (dispatched by ai_service/routes/jobs.py)

Grounded with RAG: uses rag.retrieval.retriever + rag.context_builder,
never document_chunks directly.
"""

import uuid
from typing import Any

from ai_service.rag.context_builder import BuiltContext, build_context
from ai_service.rag.retrieval.retriever import retrieve
from shared.enums import SourceType

SOURCE_TYPES = [SourceType.APPROVED_NOTE, SourceType.SYLLABUS, SourceType.TEACHER_GUIDE]


async def gather_context(query: str, topic_id: uuid.UUID | None = None, k: int = 6) -> BuiltContext:
    """Retrieve approved sources for the prompt (with citations)."""
    chunks = await retrieve(query, topic_id=topic_id, source_types=SOURCE_TYPES, k=k)
    return build_context(chunks)


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Draft an AI answer to a student question (RAG-grounded)."""
    # TODO(Mogith):
    #   1. context = await gather_context(post_title + body)
    #   2. generate a short answer with citations (add prompt community/suggested_answer.v1.j2)
    #   3. return {'body': ..., 'citations': ...} (stored as a reply with is_ai_suggested=true)
    return {"status": "todo", "pipeline": "community.suggested_answer"}
