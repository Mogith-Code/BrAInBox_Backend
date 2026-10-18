"""Rule checks + LLM reviewer for generated questions. Owner: Udith.

Job type: REVIEW_QUESTIONS (dispatched by ai_service/routes/jobs.py)

Grounded with RAG: uses rag.retrieval.retriever + rag.context_builder,
never document_chunks directly.
"""

import uuid
from typing import Any

from ai_service.rag.context_builder import BuiltContext, build_context
from ai_service.rag.retrieval.retriever import retrieve
from shared.enums import SourceType

PROMPT_NAME = "questions/review_mcq"
PROMPT_VERSION = 1


SOURCE_TYPES = [SourceType.SYLLABUS, SourceType.APPROVED_NOTE, SourceType.MARKING_SCHEME]


async def gather_context(query: str, topic_id: uuid.UUID | None = None, k: int = 6) -> BuiltContext:
    """Retrieve approved sources for the prompt (with citations)."""
    chunks = await retrieve(query, topic_id=topic_id, source_types=SOURCE_TYPES, k=k)
    return build_context(chunks)


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Rule checks + LLM reviewer for generated questions."""
    # TODO(Udith):
    #   1. basic_checks(): exactly one correct option, 5 options, no duplicates
    #   2. LLM review grounded in the same sources -> MCQReview
    #   3. return the verdicts (the api writes question_reviews rows)
    return {"status": "todo", "pipeline": "questions.quality_checks"}
