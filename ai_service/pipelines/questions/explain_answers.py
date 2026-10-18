"""Short AI feedback for every wrong or unanswered MCQ in a submitted paper. Owner: Udith.

Ported from Udith's original `app/services/explainer.py`. One LLM call explains all wrong
answers together; each item gets 2 syllabus chunks as reference.
Explanations are a bonus: if anything fails we log it and return no explanations,
so marking a paper never fails because of the AI.

Used by POST /sync/explain-mcq (ai_service/routes/sync.py).
Grounded with RAG: uses rag.retrieval.retriever, never document_chunks directly.
"""

import logging
from typing import Any

from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm
from ai_service.rag.retrieval.retriever import retrieve
from ai_service.schemas.llm_outputs import AnswerExplanationSet

logger = logging.getLogger(__name__)

PROMPT_NAME = "questions/explain_answers"
PROMPT_VERSION = 1
PROMPT_ID = prompt_id(PROMPT_NAME, PROMPT_VERSION)


async def explain_answers(items: list[dict[str, Any]]) -> dict[str, str]:
    """items = [{question_id, question, correct_answer, selected_option}] -> {question_id: text}"""
    if not items:
        return {}
    try:
        blocks = []
        for item in items:
            chunks = await retrieve(item["question"], k=2)
            blocks.append({**item, "context": "\n".join(c.text for c in chunks)})
        prompt = render_prompt(PROMPT_NAME, PROMPT_VERSION, items=blocks)
        result = await get_llm().generate_json(prompt, AnswerExplanationSet, prompt_name=PROMPT_ID)
    except Exception:
        logger.exception("Explanation step failed")
        return {}
    wanted = {str(item["question_id"]) for item in items}
    return {e.question_id: e.explanation for e in result.items if e.question_id in wanted}
