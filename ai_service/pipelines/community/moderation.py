"""Classify a community post or reply as ok, off-topic or inappropriate.

Job type: MODERATE_POST (dispatched by ai_service/routes/jobs.py); also POST /sync/moderate.

Payload: {"title": "...", "body": "..."}
Result:  {"label": "ok" | "off_topic" | "inappropriate", "allowed": bool,
          "categories": [...], "reason": "...", "prompt_version": "..."}

Anything that is not "ok" is hidden by the api until an admin decides. Most users are under 18,
so when the reviewer cannot be reached the post is held for an admin instead of being shown.
The post is passed to the model as data, never as instructions.
"""

import logging
import re
from typing import Any

from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm
from ai_service.schemas.llm_outputs import ModerationResult

logger = logging.getLogger(__name__)

PROMPT_NAME = "community/moderate_post"
PROMPT_VERSION = 2
PROMPT_ID = prompt_id(PROMPT_NAME, PROMPT_VERSION)

# Caught without an AI call: phone numbers / emails (personal data) and obvious advertising.
_PHONE_RE = re.compile(r"(?:\+94|\b0)\s?7\d(?:[\s-]?\d){7}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_SPAM_RE = re.compile(r"\b(whatsapp me|telegram group|buy now|promo code|earn money)\b", re.I)


def rule_check(text: str) -> dict[str, Any] | None:
    """Pure: an immediate verdict for the obvious cases, or None to ask the model."""
    if _PHONE_RE.search(text) or _EMAIL_RE.search(text):
        return {
            "label": "inappropriate",
            "categories": ["personal_data"],
            "reason": "It contains a phone number or email address.",
        }
    if _SPAM_RE.search(text):
        return {"label": "inappropriate", "categories": ["spam"], "reason": "It looks like spam."}
    return None


async def moderate(title: str, body: str) -> dict[str, Any]:
    text = f"{title}\n{body}".strip()
    verdict = rule_check(text)
    if verdict is None:
        try:
            prompt = render_prompt(PROMPT_NAME, PROMPT_VERSION, title=title, body=body[:4000])
            reply = await get_llm().generate_json(prompt, ModerationResult, prompt_name=PROMPT_ID)
            verdict = {
                "label": reply.label,
                "categories": reply.categories,
                "reason": reply.reason,
            }
        except Exception:
            logger.warning("Moderation model failed; holding the post for an admin", exc_info=True)
            verdict = {
                "label": "off_topic",
                "categories": ["needs_review"],
                "reason": "The automatic check was not available, so an admin will look at it.",
            }
    return {**verdict, "allowed": verdict["label"] == "ok", "prompt_version": PROMPT_ID}


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    return await moderate(str(payload.get("title") or ""), str(payload.get("body") or ""))
