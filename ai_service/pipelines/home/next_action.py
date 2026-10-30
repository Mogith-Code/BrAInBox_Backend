"""One-sentence reason for the home screen's "Next best action" card. Owner: Samni.

Called by the api (`POST /sync/next-action`). Works with the fake LLM (deterministic text).
If this fails, the api uses a template sentence (ai_generated = false).
"""

from typing import Any

from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm
from ai_service.schemas.llm_outputs import NextActionReason

PROMPT_NAME = "home/next_action"
PROMPT_VERSION = 1
PROMPT_ID = prompt_id(PROMPT_NAME, PROMPT_VERSION)


async def explain(target: dict[str, Any]) -> dict[str, Any]:
    """target = {unit_code, unit_title, topic_title, mastery} -> {"reason", "prompt_version"}"""
    prompt = render_prompt(PROMPT_NAME, PROMPT_VERSION, **target)
    output = await get_llm().generate_json(prompt, NextActionReason, prompt_name=PROMPT_ID)
    return {"reason": output.reason.strip(), "prompt_version": PROMPT_ID}
