"""Learn tab notes in block format (full or short). Owner: Samni.

Job types GENERATE_NOTES (full) and GENERATE_SHORT_NOTES (short), see generate_notes.py and
short_notes.py. Flow:
    1. render the prompt (subject, unit, topic, syllabus version, depth, toggles)
    2. ask llm_client for JSON blocks
    3. validate + repair with shared/learn_blocks.py (short notes also need 8-15 bullets)
    4. invalid -> ask ONCE more (telling the model what was wrong) -> still invalid -> fail the
       job with INVALID_AI_OUTPUT and a clear message

payload = {
    "subject": "Biology", "unit_number": 6, "unit_title": "Genetics",
    "topic_number": "6.1", "topic_title": "Mendelian inheritance", "syllabus_version": "2025",
    "depth": "quick" | "standard" | "detailed",       # full notes only
    "include_examples": true, "include_past_paper_tips": true,
}
"""

import logging
from typing import Any

from ai_service.errors import AIOutputError, UserInputError
from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm_client
from shared.learn_blocks import BlocksError, bullet_count, parse_blocks, read_minutes

logger = logging.getLogger(__name__)

FULL_PROMPT = ("notes/learn_notes", 1)
SHORT_PROMPT = ("notes/learn_short_notes", 1)
TARGET_WORDS = {"quick": 300, "standard": 900, "detailed": 1800}
MIN_BULLETS, MAX_BULLETS = 8, 15
TEMPERATURE = 0.4
RETRY_HINT = (
    "\n\nYour previous answer could not be used ({problem}). Answer again with ONLY the JSON "
    "list of blocks described above."
)


def _check_short(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Short notes: 8-15 bullets in total. More are cut to 15, fewer is an error."""
    if bullet_count(blocks) < MIN_BULLETS:
        raise BlocksError(f"short notes need at least {MIN_BULLETS} bullet points")
    remaining = MAX_BULLETS
    for block in blocks:
        if block["type"] == "bullet_list":
            block["items"] = block["items"][:remaining]
            remaining -= len(block["items"])
    return [b for b in blocks if b["type"] != "bullet_list" or b["items"]]


async def generate(payload: dict[str, Any], *, short: bool) -> dict[str, Any]:
    topic_title = (payload.get("topic_title") or "").strip()
    if not topic_title:
        raise UserInputError("topic_title is required", code="MISSING_TOPIC_TITLE")
    depth = payload.get("depth") or ("quick" if short else "standard")
    if not short and depth not in TARGET_WORDS:
        raise UserInputError(f"Unknown depth '{depth}'", code="INVALID_DEPTH")
    include_examples = bool(payload.get("include_examples", True))
    include_tips = bool(payload.get("include_past_paper_tips", True))

    name, version = SHORT_PROMPT if short else FULL_PROMPT
    prompt = render_prompt(
        name,
        version,
        subject=payload.get("subject") or "Biology",
        unit_number=payload.get("unit_number") or "",
        unit_title=payload.get("unit_title") or "",
        topic_number=payload.get("topic_number") or "",
        topic_title=topic_title,
        syllabus_version=payload.get("syllabus_version") or "current",
        target_words=TARGET_WORDS.get(depth, 900),
        include_examples=include_examples,
        include_past_paper_tips=include_tips,
    )
    task = "notes_short" if short else "notes_full"
    meta = {
        "topic_title": topic_title,
        "depth": depth,
        "include_examples": include_examples,
        "include_past_paper_tips": include_tips,
    }
    client = get_llm_client()

    problem = ""
    for attempt in range(2):  # the first try + ONE retry
        text = prompt if attempt == 0 else prompt + RETRY_HINT.format(problem=problem)
        raw = await client.complete(
            text,
            task=task,
            meta=meta,
            temperature=TEMPERATURE,
            prompt_name=prompt_id(name, version),
        )
        try:
            blocks = parse_blocks(raw)
            if short:
                blocks = _check_short(blocks)
            break
        except BlocksError as exc:
            problem = str(exc)
            logger.warning("Notes for %r invalid on try %s: %s", topic_title, attempt + 1, exc)
    else:
        raise AIOutputError(
            f"The AI returned invalid notes twice ({problem}). Please try again later."
        )

    return {
        "blocks": blocks,
        "read_minutes": read_minutes(blocks),
        "type": "short" if short else "full",
        "depth": depth,
        "model": getattr(client, "name", None),
        "prompt_version": prompt_id(name, version),
    }
