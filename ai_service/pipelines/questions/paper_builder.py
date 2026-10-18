"""Build a model paper: split the questions across topics and generate MCQs for each. Owner: Udith.

Ported from Udith's original `generate_paper()`: one topic failing (e.g. no syllabus content)
does not fail the whole paper; it becomes a warning instead.

Job type: BUILD_PAPER (dispatched by ai_service/routes/jobs.py).
The api saves the returned questions (api/modules/exams/service.py).
"""

import logging
import uuid
from typing import Any

from ai_service.pipelines.questions.generate_questions import PROMPT_ID, generate_for_topic

logger = logging.getLogger(__name__)


def split_counts(total: int, n_topics: int) -> list[int]:
    """Share `total` questions between topics as evenly as possible, e.g. 7 over 3 -> [3, 2, 2]."""
    base, extra = divmod(total, n_topics)
    return [base + (1 if i < extra else 0) for i in range(n_topics)]


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """BUILD_PAPER job.

    payload = {
        "num_questions": 20,
        "topics": [{"topic_id": "...", "title": "Photosynthesis", "unit_id": "...",
                    "examples": [{"question", "options", "correct_answer"}, ...]}, ...]
    }
    """
    topics: list[dict[str, Any]] = payload["topics"]
    counts = split_counts(int(payload["num_questions"]), len(topics))
    questions: list[dict[str, Any]] = []
    warnings: list[str] = []

    for topic, count in zip(topics, counts, strict=True):
        if count == 0:
            continue
        try:
            generated, context = await generate_for_topic(
                topic["title"],
                count,
                unit_id=uuid.UUID(topic["unit_id"]) if topic.get("unit_id") else None,
                examples=topic.get("examples"),
            )
        except Exception as exc:
            logger.warning("Paper topic %s failed: %s", topic["title"], exc)
            warnings.append(f"{topic['title']}: {exc}")
            continue
        chunk_ids = [str(c.chunk_id) for c in context.citations]
        for q in generated:
            questions.append(
                {**q.model_dump(), "topic_id": topic["topic_id"], "chunk_ids": chunk_ids}
            )
        if len(generated) < count:
            warnings.append(f"{topic['title']}: only {len(generated)} of {count} questions")

    return {"questions": questions, "warnings": warnings, "prompt_version": PROMPT_ID}
