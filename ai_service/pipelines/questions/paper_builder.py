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

from ai_service.config import get_settings
from ai_service.pipelines.questions import quality_checks
from ai_service.pipelines.questions.generate_questions import (
    DIFFICULTY_PROMPT_ID,
    PROMPT_ID,
    generate_for_topic,
)
from ai_service.pipelines.questions.generate_written import PROMPT_ID as WRITTEN_PROMPT_ID
from ai_service.pipelines.questions.generate_written import generate_written

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


async def apply_quality_gates(
    questions: list[dict[str, Any]], existing: list[str], warnings: list[str]
) -> list[dict[str, Any]]:
    """Keep only the questions that pass every gate (rules, blind review, duplicates).

    Rejected ones are dropped with a warning; the api then fills the paper with what is left.
    The reviews stay on each kept question (`quality`) so the api can store them.
    """
    if not questions:
        return questions
    try:
        reviews = await quality_checks.review_questions(questions, existing)
    except Exception as exc:  # never lose a whole paper because the reviewer is down
        logger.warning("Quality gates failed: %s", exc)
        warnings.append("Automatic quality checks were not available for this paper.")
        return questions
    kept = []
    for question, review in zip(questions, reviews, strict=True):
        if review["passed"]:
            kept.append({**question, "quality": review["checks"]})
        else:
            logger.info("Rejected generated question: %s", review["issues"])
    rejected = len(questions) - len(kept)
    if rejected:
        warnings.append(
            f"{rejected} generated question(s) failed the quality checks and were left out."
        )
    return kept


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
        unit_id_raw = unit.get("unit_id")
        try:
            unit_id = uuid.UUID(str(unit_id_raw)) if unit_id_raw else None
        except (ValueError, AttributeError):
            unit_id = None
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
        if 0 < len(unit_generated) < count:
            warnings.append(f"{unit_title}: only {len(unit_generated)} of {count} questions")

    questions = await apply_quality_gates(questions, list(payload.get("existing") or []), warnings)
    return {"questions": questions, "warnings": warnings, "prompt_version": PROMPT_ID}


# --------------------------------------------------------------------------- blueprint gaps
# Model paper blueprints (api/modules/exams/service.py): the api first takes unseen approved
# questions from the bank and only sends the GAPS here, one per (unit or topic, type, difficulty).
REVIEWER_DOWN = "Automatic quality checks were not available for this paper."


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


async def _generate_gap(gap: dict[str, Any], count: int) -> list[dict[str, Any]]:
    """Up to `count` new questions for one gap, with the gap's metadata on each."""
    kind, difficulty = str(gap["question_type"]), str(gap.get("difficulty") or "medium")
    unit_id = _uuid_or_none(gap.get("unit_id"))
    if kind == "mcq":
        mcqs, context = await generate_for_topic(
            gap["title"], count, unit_id=unit_id, examples=gap.get("examples"),
            difficulty=difficulty,
        )  # fmt: skip
        generated, prompt = [q.model_dump() for q in mcqs], DIFFICULTY_PROMPT_ID
    else:
        written, context = await generate_written(
            gap["title"], count, question_type=kind, difficulty=difficulty, unit_id=unit_id
        )
        generated, prompt = [q.model_dump() for q in written], WRITTEN_PROMPT_ID
    chunk_ids = [str(c.chunk_id) for c in context.citations]
    meta = {
        "question_type": kind,
        "difficulty": difficulty,
        "topic_id": gap.get("topic_id"),
        "unit_id": gap.get("unit_id"),
        "chunk_ids": chunk_ids,
        "prompt_version": prompt,
    }
    return [{**q, **meta} for q in generated]


async def _gated(
    items: list[dict[str, Any]], kind: str, existing: list[str], warnings: list[str]
) -> tuple[list[dict[str, Any]], int]:
    """(the items that pass every gate, how many were rejected)."""
    if not items:
        return [], 0
    review = quality_checks.review_questions if kind == "mcq" else quality_checks.review_written
    try:
        reviews = await review(items, existing)
    except Exception as exc:  # never lose a whole paper because the reviewer is down
        logger.warning("Quality gates failed: %s", exc)
        if REVIEWER_DOWN not in warnings:
            warnings.append(REVIEWER_DOWN)
        return items, 0
    kept = [
        {**q, "quality": r["checks"]} for q, r in zip(items, reviews, strict=True) if r["passed"]
    ]
    for r in reviews:
        if not r["passed"]:
            logger.info("Rejected generated question: %s", r["issues"])
    return kept, len(items) - len(kept)


async def fill_gap(
    gap: dict[str, Any], existing: list[str], warnings: list[str]
) -> list[dict[str, Any]]:
    """Generate one gap. A rejected question is regenerated ONCE; if the new one is rejected
    too it is dropped (with a warning), so the paper may come back a little short."""
    kind, count = str(gap["question_type"]), int(gap["count"])
    label = f"{gap['title']} ({kind}, {gap.get('difficulty') or 'medium'})"
    try:
        items = await _generate_gap(gap, count)
    except Exception as exc:
        logger.warning("Paper gap %s failed: %s", label, exc)
        warnings.append(f"{label}: {exc}")
        return []
    kept, rejected = await _gated(items, kind, existing, warnings)
    dropped = 0
    if rejected:
        try:
            retry = await _generate_gap(gap, rejected)
        except Exception as exc:
            logger.warning("Regenerating for %s failed: %s", label, exc)
            retry = []
        again, _ = await _gated(retry, kind, existing, warnings)
        again = again[:rejected]
        kept += again
        dropped = rejected - len(again)
        if dropped:
            warnings.append(
                f"{label}: {dropped} generated question(s) failed the quality checks twice "
                "and were left out."
            )
    if len(kept) + dropped < count:
        warnings.append(f"{label}: only {len(kept)} of {count} questions")
    return kept[:count]


async def build_from_gaps(payload: dict[str, Any]) -> dict[str, Any]:
    """BUILD_PAPER for a model paper blueprint: fill every gap, in order."""
    existing = list(payload.get("existing") or [])
    # Offline, the fake LLM writes the same question every time: comparing gaps with each other
    # would reject everything (like the within-batch rule in quality_checks.duplicate_checks).
    compare_gaps = not get_settings().use_fakes
    questions: list[dict[str, Any]] = []
    warnings: list[str] = []
    for gap in payload.get("gaps") or []:
        if int(gap.get("count") or 0) <= 0:
            continue
        seen = existing + ([str(q["question"]) for q in questions] if compare_gaps else [])
        questions.extend(await fill_gap(gap, seen, warnings))
    return {
        "questions": questions,
        "warnings": warnings,
        "prompt_version": DIFFICULTY_PROMPT_ID,
        "prompt_versions": sorted({str(q["prompt_version"]) for q in questions}),
    }


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """BUILD_PAPER job.

    Model paper blueprint (POST /api/v1/papers/generate):
        payload = {
            "gaps": [{"question_type": "mcq" | "structured" | "essay",
                      "difficulty": "easy" | "medium" | "hard", "count": 3, "title": "...",
                      "unit_id": "..."?, "topic_id": "..."?}, ...],
            "existing": ["stems already on the paper / in the bank", ...]
        }

    Topic-based paper building:
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
    if payload.get("gaps") is not None:
        return await build_from_gaps(payload)
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

    questions = await apply_quality_gates(questions, list(payload.get("existing") or []), warnings)
    return {"questions": questions, "warnings": warnings, "prompt_version": PROMPT_ID}
