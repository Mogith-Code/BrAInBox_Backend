"""Rank candidate resources (e.g. YouTube results) for weak concepts. Owner: Udith.

Job type: RANK_RESOURCES (dispatched by ai_service/routes/jobs.py)
"""

from typing import Any


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Rank candidate resources (e.g. YouTube results) for weak concepts."""
    # TODO(Udith):
    #   1. score each candidate for relevance to the weak concepts (embeddings or LLM)
    #   2. return resources sorted by score with a short reason
    return {"status": "todo", "pipeline": "recommendations.rank_resources"}
