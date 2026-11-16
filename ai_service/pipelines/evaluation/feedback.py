"""Write student-friendly improvement tips for a marked answer.

The marks are already decided (scorer.py). The LLM only sees the points that were missing or
partly covered and writes tips for them; whatever it answers, the marks stay the same. If the
LLM fails, the student still gets plain tips built from the marking points.

Grounded with RAG: uses rag.retrieval.retriever + rag.context_builder, never document_chunks
directly. The student's answer is passed as data inside the prompt, never as instructions.
"""

import logging
import uuid
from typing import Any

from ai_service.config import get_settings
from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm
from ai_service.rag.context_builder import BuiltContext, build_context
from ai_service.rag.retrieval.retriever import retrieve
from ai_service.schemas.llm_outputs import EvaluationFeedback
from shared.enums import SourceType

logger = logging.getLogger(__name__)

PROMPT_NAME = "evaluation/feedback"
PROMPT_VERSION = 2
MAX_TIPS = 5

SOURCE_TYPES = [SourceType.MARKING_SCHEME, SourceType.TEACHER_GUIDE]


async def gather_context(query: str, topic_id: uuid.UUID | None = None, k: int = 6) -> BuiltContext:
    """Retrieve approved sources for the prompt (with citations)."""
    chunks = await retrieve(query, topic_id=topic_id, source_types=SOURCE_TYPES, k=k)
    return build_context(chunks)


def template_tips(results: list[dict[str, Any]]) -> list[str]:
    """Pure: tips without an LLM, one per point that was not fully covered."""
    tips = []
    for r in results:
        if r["status"] == "missing" and r.get("problem") == "wrong_application":
            tips.append(f"You used the right terms, but explain how they apply here: {r['text']}")
        elif r["status"] == "missing":
            tips.append(f"Add this point: {r['text']}")
        elif r["status"] == "partial":
            tips.append(f"Make this point complete and precise: {r['text']}")
    return tips[:MAX_TIPS]


def template_summary(results: list[dict[str, Any]]) -> str:
    covered = sum(1 for r in results if r["status"] == "covered")
    partial = sum(1 for r in results if r["status"] == "partial")
    missing = len(results) - covered - partial
    parts = [f"You covered {covered} of {len(results)} marking points"]
    if partial:
        parts.append(f"{partial} only partly")
    if missing:
        parts.append(f"{missing} missing")
    return ", ".join(parts) + "."


async def _context_text(question: str, topic_id: Any) -> str:
    try:
        topic = uuid.UUID(str(topic_id)) if topic_id else None
        return (await gather_context(question, topic)).text
    except Exception:  # no database / nothing ingested yet: tips still work without sources
        logger.info("No reference material for the feedback prompt", exc_info=True)
        return ""


async def write_feedback(
    *, question: str, answer: str, results: list[dict[str, Any]], topic_id: Any = None
) -> dict[str, Any]:
    """{"feedback", "tips", "strengths", "ai_generated", "prompt_version", "model"}."""
    covered = [r["text"] for r in results if r["status"] == "covered"]
    to_fix = [r for r in results if r["status"] != "covered"]
    out: dict[str, Any] = {
        "feedback": template_summary(results),
        "tips": template_tips(results),
        "strengths": covered[:MAX_TIPS],
        "ai_generated": False,
        "prompt_version": prompt_id(PROMPT_NAME, PROMPT_VERSION),
        "model": None,
    }
    if not to_fix:  # full marks: nothing for the LLM to add
        out["feedback"] = "You covered every marking point. Well done!"
        return out
    settings = get_settings()
    try:
        prompt = render_prompt(
            PROMPT_NAME,
            PROMPT_VERSION,
            question=question,
            answer=answer[: settings.MAX_INPUT_CHARS],
            covered_points=covered,
            partial_points=[r["text"] for r in to_fix if r["status"] == "partial"],
            missing_points=[r["text"] for r in to_fix if r["status"] == "missing"],
            context=await _context_text(question, topic_id),
        )
        reply = await get_llm().generate_json(
            prompt, EvaluationFeedback, prompt_name=out["prompt_version"]
        )
    except Exception:
        logger.warning("Feedback tips from the LLM failed; using the template", exc_info=True)
        return out
    tips = [t.strip() for t in reply.improvements if t.strip()][:MAX_TIPS]
    if reply.feedback.strip() and tips:
        out.update(
            feedback=reply.feedback.strip(),
            tips=tips,
            ai_generated=True,
            model=getattr(get_llm(), "model", None) or getattr(get_llm(), "name", None),
        )
    return out
