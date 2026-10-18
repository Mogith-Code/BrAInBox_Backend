"""Combine keyword + semantic matches into estimated marks. Owner: Keshomigha.

Job type: EVALUATE_ANSWER (dispatched by ai_service/routes/jobs.py)
"""

from typing import Any


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Combine keyword + semantic matches into estimated marks."""
    # TODO(Keshomigha):
    #   1. matched = keyword_match + semantic_match per answer point
    #   2. marks = sum of matched point marks (capped at max)
    #   3. feedback = await feedback.write_feedback(...)
    #   4. return {'estimated_marks', 'matched_points', 'feedback'}
    return {"status": "todo", "pipeline": "evaluation.scorer"}
