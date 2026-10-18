"""Write student-friendly feedback grounded in marking schemes. Owner: Keshomigha.

Grounded with RAG: uses rag.retrieval.retriever + rag.context_builder,
never document_chunks directly.
"""

import uuid

from ai_service.rag.context_builder import BuiltContext, build_context
from ai_service.rag.retrieval.retriever import retrieve
from shared.enums import SourceType

PROMPT_NAME = "evaluation/feedback"
PROMPT_VERSION = 1


SOURCE_TYPES = [SourceType.MARKING_SCHEME, SourceType.TEACHER_GUIDE]


async def gather_context(query: str, topic_id: uuid.UUID | None = None, k: int = 6) -> BuiltContext:
    """Retrieve approved sources for the prompt (with citations)."""
    chunks = await retrieve(query, topic_id=topic_id, source_types=SOURCE_TYPES, k=k)
    return build_context(chunks)


# TODO(Keshomigha):
#   1. context = await gather_context(question_text)
#   2. render_prompt(PROMPT_NAME, ...) -> get_llm().generate_json(prompt, EvaluationFeedback)
