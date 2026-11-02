"""Build a model paper: split questions across topics or units and generate MCQs for each. Owner: Udith.

Ported and enhanced from Udith's original `generate_paper()` and `generate_paper_by_units()`:
one topic or unit failing (e.g. no syllabus content) does not fail the whole paper; it becomes
a warning instead.

Job type: BUILD_PAPER (dispatched by ai_service/routes/jobs.py).
The api saves the returned questions (api/modules/exams/service.py).
"""

import logging
import uuid
from typing import Any

from ai_service.pipelines.questions.generate_questions import PROMPT_ID, generate_for_topic

logger = logging.getLogger(__name__)

BATCH_SIZE = 5  # questions per LLM call (unit papers)


def split_counts(total: int, n_parts: int) -> list[int]:
    """Share `total` questions between parts as evenly as possible, e.g. 7 over 3 -> [3, 2, 2]."""
    base, extra = divmod(total, n_parts)
    return [base + (1 if i < extra else 0) for i in range(n_parts)]


def batch_sizes(n: int) -> list[int]:
    """Split `n` into batches of at most BATCH_SIZE."""
    full, rest = divmod(n, BATCH_SIZE)
    return [BATCH_SIZE] * full + ([rest] if rest else [])


async def _build_from_units(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate paper by units using batching and RAG grounding."""
    units: list[dict[str, Any]] = payload["units"]
    total = int(payload["num_questions"])
    counts = split_counts(total, len(units))
    questions: list[dict[str, Any]] = []
    warnings: list[str] = []

    for unit, count in zip(units, counts, strict=True):
        if count == 0:
            continue
        unit_id = uuid.UUID(unit["unit_id"]) if unit.get("unit_id") else None
        unit_no = unit.get("unit_number")
        unit_title = str(unit.get("title") or f"Unit {unit_no}").strip()

        unit_generated: list[dict[str, Any]] = []
        for b_count in batch_sizes(count):
            try:
                generated, context = await generate_for_topic(
                    unit_title,
                    b_count,
                    unit_id=unit_id,
                    examples=unit.get("examples"),
                )
            except Exception as exc:
                logger.warning("Paper unit %s failed: %s", unit_title, exc)
                warnings.append(f"{unit_title}: {exc}")
                continue

            chunk_ids = [str(c.chunk_id) for c in context.citations]
            for q in generated:
                unit_generated.append(
                    {
                        **q.model_dump(),
                        "topic_id": unit.get("topic_id"),
                        "unit_id": str(unit_id) if unit_id else None,
                        "unit_number": unit_no,
                        "chunk_ids": chunk_ids,
                    }
                )

        questions.extend(unit_generated)
        if len(unit_generated) < count:
            warnings.append(f"{unit_title}: only {len(unit_generated)} of {count} questions")

    return {"questions": questions, "warnings": warnings, "prompt_version": PROMPT_ID}


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """BUILD_PAPER job.

    Supports both topic-based paper building:
        payload = {
            "num_questions": 20,
            "topics": [{"topic_id": "...", "title": "Photosynthesis", "unit_id": "...",
                        "examples": [{"question", "options", "correct_answer"}, ...]}, ...]
        }

    And unit-based paper building:
        payload = {
            "num_questions": 20,
            "units": [{"unit_id": "...", "unit_number": 1, "title": "Introduction to Biology"}, ...]
        }
    """
    if "units" in payload and payload["units"]:
        return await _build_from_units(payload)

    topics: list[dict[str, Any]] = payload.get("topics", [])
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
