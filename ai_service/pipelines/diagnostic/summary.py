"""2-sentence summary of a diagnostic result. Owner: Udith.

Called by the api (`POST /sync/diagnostic-summary`) when a student submits the diagnostic.
Works with the fake LLM (deterministic text). If this fails, the api uses a template sentence.
"""

from typing import Any

from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm
from ai_service.schemas.llm_outputs import DiagnosticSummary

PROMPT_NAME = "diagnostic/summary"
PROMPT_VERSION = 1
PROMPT_ID = prompt_id(PROMPT_NAME, PROMPT_VERSION)


async def summarize(result: dict[str, Any]) -> dict[str, Any]:
    """result = {score, total, strongest, needs_work, units} -> {"summary", "prompt_version"}"""
    prompt = render_prompt(PROMPT_NAME, PROMPT_VERSION, **result)
    output = await get_llm().generate_json(prompt, DiagnosticSummary, prompt_name=PROMPT_ID)
    return {"summary": output.summary.strip(), "prompt_version": PROMPT_ID}
