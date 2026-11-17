"""Estimate the marks of a written answer from its marking points.

Job type: EVALUATE_ANSWER (dispatched by ai_service/routes/jobs.py)

Payload (built by api/modules/evaluation/service.py):
    {
      "question": "Describe active transport.",
      "answer_text": "...",
      "max_marks": 6,
      "topic_id": "<uuid>" | null,
      "points": [
        {"id": "<uuid>", "text": "ATP is used", "marks": 1, "is_required": false,
         "keywords": [{"keyword": "ATP", "synonyms": ["adenosine triphosphate"]}]}
      ]
    }

Each marking point is checked two ways: its keywords (keyword_match.py) and its meaning
(semantic_match.py). The rule that turns both into marks:

    covered  if similarity >= 0.80, or (keyword hit and similarity >= 0.65)   -> full marks
    partial  if 0.65 <= similarity < 0.80                                     -> half marks
    missing  otherwise                                                        -> no marks
    estimated_marks = sum(point.marks x coverage), capped at the question's marks

The thresholds are starting values (EVAL_COVERED_SIMILARITY / EVAL_PARTIAL_SIMILARITY), tuned
with scripts/eval_accuracy.py. The LLM only writes the improvement tips afterwards: it never
sees or changes the marks.
"""

from typing import Any

from ai_service.config import get_settings
from ai_service.errors import UserInputError
from ai_service.pipelines.evaluation import feedback
from ai_service.pipelines.evaluation.keyword_match import keyword_hits
from ai_service.pipelines.evaluation.semantic_match import Match, best_matches

COVERED, PARTIAL, MISSING = "covered", "partial", "missing"
MIN_ANSWER_CHARS = 3


def coverage(
    similarity: float, keyword_hit: bool, covered_at: float, partial_at: float
) -> tuple[str, float]:
    """Pure: (status, share of the point's marks)."""
    if similarity >= covered_at or (keyword_hit and similarity >= partial_at):
        return COVERED, 1.0
    if similarity >= partial_at:
        return PARTIAL, 0.5
    return MISSING, 0.0


def problem_for(status: str, keyword_hit: bool) -> str | None:
    """Pure: what kind of mistake a point that was not fully covered is.

    * keywords are there but the meaning does not match -> `wrong_application`
    * about half right                                  -> `incomplete`
    * nothing about it                                  -> `missing_concept`
    """
    if status == COVERED:
        return None
    if status == PARTIAL:
        return "incomplete"
    return "wrong_application" if keyword_hit else "missing_concept"


def score_points(
    points: list[dict[str, Any]],
    matches: list[Match],
    answer: str,
    *,
    covered_at: float,
    partial_at: float,
) -> list[dict[str, Any]]:
    """Pure: one result per marking point, in marking-scheme order."""
    results = []
    for point, match in zip(points, matches, strict=True):
        words = [k["keyword"] for k in point.get("keywords", [])]
        synonyms = {k["keyword"]: list(k.get("synonyms") or []) for k in point.get("keywords", [])}
        hits = keyword_hits(answer, words, synonyms)
        status, share = coverage(match.similarity, bool(hits), covered_at, partial_at)
        marks = float(point.get("marks") or 1)
        results.append(
            {
                "answer_point_id": point["id"],
                "text": point["text"],
                "marks": marks,
                "status": status,
                "matched": status == COVERED,
                "score": share,
                "marks_awarded": round(marks * share, 2),
                "similarity": match.similarity,
                "has_keywords": bool(words),
                "keyword_hit": bool(hits),
                "matched_keywords": hits,
                "evidence": match.evidence if status != MISSING else "",
                "position": match.position if status != MISSING else -1,
                "is_required": bool(point.get("is_required")),
                "problem": problem_for(status, bool(hits)),
            }
        )
    return results


def structure_check(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure: are the covered points in the marking scheme's order, and is a required one absent?"""
    positions = [r["position"] for r in results if r["status"] != MISSING and r["position"] >= 0]
    in_order = all(a <= b for a, b in zip(positions, positions[1:], strict=False))
    missing_required = [
        r["answer_point_id"] for r in results if r["is_required"] and r["status"] == MISSING
    ]
    return {
        "in_order": in_order,
        "missing_required": missing_required,
        "ok": in_order and not missing_required,
    }


def totals(results: list[dict[str, Any]], max_marks: float) -> dict[str, float]:
    """Pure: estimated marks (capped) and the two 0..1 scores stored with the evaluation."""
    awarded = sum(r["marks_awarded"] for r in results)
    keyword_points = [r for r in results if r["has_keywords"]]
    keyword_share = (
        sum(1 for r in keyword_points if r["keyword_hit"]) / len(keyword_points)
        if keyword_points
        else 0.0
    )
    semantic = sum(r["similarity"] for r in results) / len(results) if results else 0.0
    # Confident when points are clearly covered or clearly missing; unsure near the thresholds.
    clear = sum(1 for r in results if r["status"] != PARTIAL) / len(results) if results else 0.0
    return {
        "estimated_marks": round(min(awarded, max_marks), 2),
        "keyword_coverage": round(keyword_share, 3),
        "semantic_score": round(semantic, 3),
        "confidence": round(0.5 + 0.5 * clear, 3),
    }


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Estimate marks, then ask the LLM for tips on the missing / partial points only."""
    answer = str(payload.get("answer_text") or "").strip()
    points = list(payload.get("points") or [])
    if len(answer) < MIN_ANSWER_CHARS:
        raise UserInputError("Write your answer first, then check it.", code="EMPTY_ANSWER")
    if not points:
        raise UserInputError(
            "This question has no marking scheme yet, so it can't be checked.",
            code="NO_MARKING_POINTS",
        )
    settings = get_settings()
    max_marks = float(payload.get("max_marks") or sum(float(p.get("marks") or 1) for p in points))

    matches = await best_matches(answer, [p["text"] for p in points])
    results = score_points(
        points,
        matches,
        answer,
        covered_at=settings.EVAL_COVERED_SIMILARITY,
        partial_at=settings.EVAL_PARTIAL_SIMILARITY,
    )
    summary = totals(results, max_marks)
    tips = await feedback.write_feedback(
        question=str(payload.get("question") or ""),
        answer=answer,
        results=results,
        topic_id=payload.get("topic_id"),
    )
    return {
        "method": "hybrid",
        "max_marks": max_marks,
        **summary,
        "points": results,
        "structure": structure_check(results),
        **tips,
    }
