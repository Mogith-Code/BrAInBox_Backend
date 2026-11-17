"""Suggest the syllabus topic a community post is about (fast sync call, POST /sync/tag-post).

The api sends the post and the topics to choose from; the best match by meaning (embeddings)
is suggested. The student can change it before posting. Nothing is suggested when no topic is a
reasonable match, e.g. for a post in the general group about exam stress.
"""

from typing import Any

from ai_service.pipelines.evaluation.semantic_match import cosine
from ai_service.providers import get_embedder

MIN_SCORE = 0.30
MAX_TEXT_CHARS = 2000


async def tag_post(
    title: str, body: str, topics: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """topics = [{"id", "title", "unit_number"}] -> {"topic_id", "topic_title", "unit_number",
    "tags", "confidence"} (all null / empty when nothing matches)."""
    empty: dict[str, Any] = {
        "topic_id": None,
        "topic_title": None,
        "unit_number": None,
        "tags": [],
        "confidence": 0.0,
    }
    text = f"{title}\n{body}".strip()[:MAX_TEXT_CHARS]
    if not text or not topics:
        return empty
    embedder = get_embedder()
    post_vector = (await embedder.embed([text], task="query"))[0]
    topic_vectors = await embedder.embed([str(t["title"]) for t in topics])
    scores = [cosine(post_vector, v) for v in topic_vectors]
    best = max(range(len(scores)), key=lambda i: scores[i])
    if scores[best] < MIN_SCORE:
        return empty
    topic = topics[best]
    return {
        "topic_id": str(topic["id"]),
        "topic_title": topic["title"],
        "unit_number": topic.get("unit_number"),
        "tags": [topic["title"]],
        "confidence": round(scores[best], 3),
    }
