"""Generate full notes for a topic. Owner: Samni.

Job type: GENERATE_NOTES (dispatched by ai_service/routes/jobs.py)

Learn tab: block-format notes from llm_client (learn_notes.py). `gather_context` (RAG
grounding) is kept for the admin-reviewed notes flow.
"""

import uuid
from typing import Any

from ai_service.pipelines.notes import learn_notes
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
    """Learn tab full notes as JSON blocks (see learn_notes.py for the payload)."""
    return await learn_notes.generate(payload, short=False)
