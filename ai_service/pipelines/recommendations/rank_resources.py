"""Rank candidate videos for a weak concept and drop the ones that do not match it.

Job type: RANK_RESOURCES (dispatched by ai_service/routes/jobs.py); also POST /sync/rank-resources.

Payload:
    {"concept": "Active transport", "topic": "Cell membrane",
     "candidates": [{"id": "abc123", "title": "...", "description": "..."}], "limit": 2}
Result:
    {"resources": [{"id": "abc123", "score": 0.71, "reason": "..."}]}   # best first

The score is the cosine similarity between the concept and the video's title + description.
Videos below MIN_SCORE are weak matches and are left out, so a student is never sent to an
unrelated video just because the search returned it.
"""

from typing import Any

from ai_service.pipelines.evaluation.keyword_match import normalise
from ai_service.pipelines.evaluation.semantic_match import cosine
from ai_service.providers import get_embedder

MIN_SCORE = 0.45
TITLE_BONUS = 0.10  # the concept's own words in the title are a strong sign


def title_overlap(concept: str, title: str) -> float:
    """Pure: share (0..1) of the concept's word stems that appear in the title."""
    wanted = set(normalise(concept))
    if not wanted:
        return 0.0
    return len(wanted & set(normalise(title))) / len(wanted)


async def rank(
    concept: str, topic: str | None, candidates: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    embedder = get_embedder()
    query = f"A/L Biology {topic + ': ' if topic else ''}{concept}"
    query_vector = (await embedder.embed([query], task="query"))[0]
    texts = [f"{c.get('title', '')}. {str(c.get('description') or '')[:500]}" for c in candidates]
    vectors = await embedder.embed(texts)
    ranked = []
    for candidate, vector in zip(candidates, vectors, strict=True):
        overlap = title_overlap(concept, str(candidate.get("title") or ""))
        score = min(1.0, cosine(query_vector, vector) + TITLE_BONUS * overlap)
        if score >= MIN_SCORE:
            ranked.append(
                {
                    "id": candidate.get("id"),
                    "score": round(score, 3),
                    "reason": (
                        f"Its title covers “{concept}”."
                        if overlap >= 0.5
                        else f"It is closely related to “{concept}”."
                    ),
                }
            )
    ranked.sort(key=lambda r: -r["score"])
    return ranked[:limit]


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    resources = await rank(
        str(payload.get("concept") or ""),
        payload.get("topic"),
        list(payload.get("candidates") or []),
        int(payload.get("limit") or 2),
    )
    return {"resources": resources}
