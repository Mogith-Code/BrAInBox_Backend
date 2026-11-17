"""Generate A/L structured / essay questions with a model answer and a marking scheme.

Owner: Udith. Used by paper_builder.py (BUILD_PAPER, model paper blueprints) for the
structured and essay parts. Grounded with RAG exactly like generate_questions.py: no approved
source text -> no questions.

Each question comes with `points` (one checkable idea each, whole marks, 1-4 keywords) whose
marks add up to the question's marks, so the evaluation pipeline can mark a student's answer
with it straight away (the api stores it as an AI model answer, pending review).
"""

import uuid

from pydantic import ValidationError

from ai_service.pipelines.questions.generate_questions import NoContextError, gather_context
from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm
from ai_service.rag.context_builder import BuiltContext
from ai_service.schemas.llm_outputs import GeneratedWrittenQuestion, GeneratedWrittenSet

PROMPT_NAME = "questions/generate_written"
PROMPT_VERSION = 1
PROMPT_ID = prompt_id(PROMPT_NAME, PROMPT_VERSION)

QUESTION_TYPES = ("structured", "essay")
MAX_RETRIES = 2  # extra attempts when the LLM returns invalid questions
TEMPERATURE = 0.7


async def generate_written(
    topic_title: str,
    count: int,
    *,
    question_type: str,
    difficulty: str = "medium",
    unit_id: uuid.UUID | None = None,
) -> tuple[list[GeneratedWrittenQuestion], BuiltContext]:
    """Up to `count` validated written questions and the context they came from."""
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"question_type must be one of {QUESTION_TYPES}")
    context = await gather_context(topic_title, unit_id)
    if not context.citations:
        raise NoContextError(f"No syllabus content found for topic '{topic_title}'")
    prompt = render_prompt(
        PROMPT_NAME,
        PROMPT_VERSION,
        topic_title=topic_title,
        count=count,
        question_type=question_type,
        difficulty=difficulty,
        context=context.text,
    )
    last_error: Exception | None = None
    for _ in range(MAX_RETRIES + 1):
        try:
            result = await get_llm().generate_json(
                prompt, GeneratedWrittenSet, temperature=TEMPERATURE, prompt_name=PROMPT_ID
            )
            return result.questions[:count], context
        except ValidationError as exc:  # bad JSON, or points that don't add up to the marks
            last_error = exc
    raise RuntimeError(f"LLM output was invalid after retries: {last_error}")
