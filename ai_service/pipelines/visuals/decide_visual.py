"""Decide which kind of visual fits a concept, then build it. Owner: Mogith.

Job type: GENERATE_VISUAL (dispatched by ai_service/routes/jobs.py)
"""

from typing import Any

PROMPT_NAME = "visuals/decide_visual"
PROMPT_VERSION = 1


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Decide which kind of visual fits a concept, then build it."""
    # TODO(Mogith):
    #   1. decision = await get_llm().generate_json(render_prompt(PROMPT_NAME, ...), VisualDecision)
    #   2. diagram / flowchart -> diagram_mermaid.validate_mermaid(decision.mermaid_code)
    #   3. illustration -> illustration.create_illustration(decision.image_prompt)
    #   4. return {'kind': ..., 'mermaid_code' | 'image_path': ...}
    return {"status": "todo", "pipeline": "visuals.decide_visual"}
