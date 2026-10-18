"""Generate A/L-style MCQs for a topic. Owner: Udith.

Job type: GENERATE_QUESTIONS (dispatched by ai_service/routes/jobs.py)

Grounded with RAG: uses rag.retrieval.retriever + rag.context_builder,
never document_chunks directly.
"""

import uuid
from typing import Any

from ai_service.rag.context_builder import BuiltContext, build_context
from ai_service.rag.retrieval.retriever import retrieve
from shared.enums import SourceType

PROMPT_NAME = "questions/generate_mcq"
PROMPT_VERSION = 1


SOURCE_TYPES = [SourceType.SYLLABUS, SourceType.APPROVED_NOTE, SourceType.MARKING_SCHEME]


async def gather_context(query: str, topic_id: uuid.UUID | None = None, k: int = 6) -> BuiltContext:
    """Retrieve approved sources for the prompt (with citations)."""
    chunks = await retrieve(query, topic_id=topic_id, source_types=SOURCE_TYPES, k=k)
    return build_context(chunks)


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate A/L-style MCQs for a topic."""
    # TODO(Udith):
    #   1. context = await gather_context(topic_title, topic_id)
    #   2. mcqs = await get_llm().generate_json(prompt, GeneratedMCQSet)
    #   3. run quality_checks.basic_checks on every question
    #   4. return questions + citations (saved as drafts for admin review)
    return {"status": "todo", "pipeline": "questions.generate_questions"}
