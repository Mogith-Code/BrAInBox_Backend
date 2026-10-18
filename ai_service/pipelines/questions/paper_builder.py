"""Assemble a model paper from approved questions. Owner: Udith.

Job type: BUILD_PAPER (dispatched by ai_service/routes/jobs.py)
"""

from typing import Any


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Assemble a model paper from approved questions."""
    # TODO(Udith):
    #   1. pick questions by unit weighting + difficulty mix from the payload
    #   2. return ordered question ids + marks
    return {"status": "todo", "pipeline": "questions.paper_builder"}
