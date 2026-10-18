"""Check a post for unsafe content. Owner: Mogith.

Job type: MODERATE_POST (dispatched by ai_service/routes/jobs.py)
"""

from typing import Any

PROMPT_NAME = "community/moderate_post"
PROMPT_VERSION = 1


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Check a post for unsafe content."""
    # TODO(Mogith):
    #   1. get_llm().generate_json(render_prompt(PROMPT_NAME, ...), ModerationResult)
    #   2. return {'allowed', 'categories', 'reason'}
    return {"status": "todo", "pipeline": "community.moderation"}
