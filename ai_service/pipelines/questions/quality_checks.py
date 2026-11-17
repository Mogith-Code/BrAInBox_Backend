"""Quality gates for generated MCQs: rule checks, a blind AI review, a duplicate check and a
syllabus check.

Job type: REVIEW_QUESTIONS (dispatched by ai_service/routes/jobs.py). The paper builder also
calls `review_questions()` directly, so every generated question passes the same gates.

Payload:
    {
      "questions": [{"id"?, "question", "options": [...], "correct_answer",
                     "allow_all_of_above"?: false, "outdated"?: false}],
      "existing": ["stem of a question already in the bank", ...]   # for the duplicate check
    }
Result: {"reviews": [{"index", "question_id", "passed", "verdict", "issues", "checks": {...}}]}
"""

import logging
import re
from typing import Any

from ai_service.config import get_settings
from ai_service.pipelines.evaluation.semantic_match import cosine
from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_embedder, get_llm
from ai_service.schemas.llm_outputs import BlindAnswer

logger = logging.getLogger(__name__)

PROMPT_NAME = "questions/blind_answer"
PROMPT_VERSION = 1
PROMPT_ID = prompt_id(PROMPT_NAME, PROMPT_VERSION)

OPTION_COUNT = 5  # A/L MCQs have exactly five options
MAX_STEM_CHARS = 600
MAX_OPTION_CHARS = 200
_CATCH_ALL_RE = re.compile(r"\b(all|none|both) of the (above|these|following)\b", re.I)


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def rule_issues(question: dict[str, Any]) -> list[str]:
    """Pure: everything wrong with the shape of one MCQ (empty list = fine)."""
    issues = []
    stem = str(question.get("question") or "").strip()
    options = [str(o).strip() for o in (question.get("options") or [])]
    answer = str(question.get("correct_answer") or "").strip()
    if not stem:
        issues.append("The question text is empty.")
    if len(stem) > MAX_STEM_CHARS:
        issues.append(f"The question is longer than {MAX_STEM_CHARS} characters.")
    if len(options) != OPTION_COUNT:
        issues.append(f"It has {len(options)} options; A/L MCQs need exactly {OPTION_COUNT}.")
    if any(not o for o in options):
        issues.append("An option is empty.")
    if any(len(o) > MAX_OPTION_CHARS for o in options):
        issues.append(f"An option is longer than {MAX_OPTION_CHARS} characters.")
    normalised = [_norm(o) for o in options]
    if len(set(normalised)) != len(normalised):
        issues.append("Two options are the same.")
    if sum(1 for o in options if o == answer) != 1:
        issues.append("Exactly one option must be the correct answer.")
    if not question.get("allow_all_of_above") and any(_CATCH_ALL_RE.search(o) for o in options):
        issues.append('"All / none of the above" options are not allowed here.')
    return issues


async def blind_check(question: dict[str, Any]) -> dict[str, Any]:
    """Ask the LLM to answer WITHOUT the key. A different answer means the question is unclear
    or the key is wrong. Skipped (passed = None) with the fake LLM, which cannot reason."""
    if get_settings().use_fakes:
        return {"passed": None, "skipped": "fake AI"}
    options = [str(o) for o in question["options"]]
    prompt = render_prompt(
        PROMPT_NAME, PROMPT_VERSION, question=question["question"], options=options
    )
    try:
        reply = await get_llm().generate_json(
            prompt, BlindAnswer, temperature=0.0, prompt_name=PROMPT_ID
        )
    except Exception:
        logger.warning("Blind review failed; the question is not rejected for it", exc_info=True)
        return {"passed": None, "skipped": "reviewer unavailable"}
    index = reply.answer_index
    chosen = options[index] if 0 <= index < len(options) else None
    return {
        "passed": chosen == question["correct_answer"],
        "reviewer_answer": chosen,
        "confidence": reply.confidence,
    }


async def duplicate_checks(stems: list[str], existing: list[str]) -> list[dict[str, Any]]:
    """For each stem: is it (nearly) the same as a bank question or an earlier one in the batch?"""
    if not stems:
        return []
    threshold = get_settings().QUESTION_DUPLICATE_SIMILARITY
    embedder = get_embedder()
    vectors = await embedder.embed(stems)
    known = await embedder.embed(existing) if existing else []
    # The fake LLM returns the same sample question every time, so comparing a batch with
    # itself would reject everything in offline dev. Bank duplicates are still checked.
    within_batch = not get_settings().use_fakes
    out = []
    for i, vector in enumerate(vectors):
        best, similar = 0.0, None
        others = list(zip(existing, known, strict=True))
        if within_batch:
            others += list(zip(stems[:i], vectors[:i], strict=True))
        for text, other in others:
            score = cosine(vector, other)
            if score > best:
                best, similar = score, text
        out.append(
            {
                "passed": best < threshold,
                "similarity": round(best, 3),
                "similar_to": similar if best >= threshold else None,
            }
        )
    return out


async def review_questions(
    questions: list[dict[str, Any]], existing: list[str] | None = None
) -> list[dict[str, Any]]:
    """Run all four gates on every question."""
    duplicates = await duplicate_checks(
        [str(q.get("question") or "") for q in questions], existing or []
    )
    reviews = []
    for index, (question, duplicate) in enumerate(zip(questions, duplicates, strict=True)):
        rules = rule_issues(question)
        # No point asking the reviewer about a question that is already malformed.
        blind = await blind_check(question) if not rules else {"passed": None, "skipped": "rules"}
        syllabus_ok = not question.get("outdated")
        issues = list(rules)
        if blind["passed"] is False:
            issues.append(
                "A blind reviewer chose a different answer than the key: "
                f"{blind.get('reviewer_answer')!r}."
            )
        if not duplicate["passed"]:
            issues.append("It is almost the same as an existing question.")
        if not syllabus_ok:
            issues.append("Its concept is marked outdated in the syllabus.")
        reviews.append(
            {
                "index": index,
                "question_id": question.get("id"),
                "passed": not issues,
                "verdict": "accept" if not issues else "reject",
                "issues": issues,
                "checks": {
                    "rules": {"passed": not rules, "issues": rules},
                    "blind_review": blind,
                    "duplicate": duplicate,
                    "syllabus": {"passed": syllabus_ok},
                },
            }
        )
    return reviews


# --------------------------------------------------------------------------- written questions
MAX_WRITTEN_STEM_CHARS = 1500
WRITTEN_MARKS = {"structured": (1, 10), "essay": (5, 20)}


def written_rule_issues(question: dict[str, Any]) -> list[str]:
    """Pure: everything wrong with the shape of one structured / essay question."""
    issues = []
    stem = str(question.get("question") or "").strip()
    kind = str(question.get("question_type") or "structured")
    marks = question.get("marks")
    points = [p for p in (question.get("points") or []) if isinstance(p, dict)]
    if not stem:
        issues.append("The question text is empty.")
    if len(stem) > MAX_WRITTEN_STEM_CHARS:
        issues.append(f"The question is longer than {MAX_WRITTEN_STEM_CHARS} characters.")
    if not str(question.get("model_answer") or "").strip():
        issues.append("It has no model answer.")
    low, high = WRITTEN_MARKS.get(kind, (1, 20))
    if not isinstance(marks, int) or not low <= marks <= high:
        issues.append(f"A {kind} question should be worth {low}-{high} marks.")
    if len(points) < 2:
        issues.append("The marking scheme needs at least 2 points.")
    if any(not str(p.get("text") or "").strip() for p in points):
        issues.append("A marking point is empty.")
    if any(not [k for k in p.get("keywords") or [] if str(k).strip()] for p in points):
        issues.append("Every marking point needs at least one keyword.")
    if isinstance(marks, int) and sum(int(p.get("marks") or 0) for p in points) != marks:
        issues.append("The marking points don't add up to the question's marks.")
    return issues


async def review_written(
    questions: list[dict[str, Any]], existing: list[str] | None = None
) -> list[dict[str, Any]]:
    """Rule checks + the duplicate check for written questions (no blind review: there is no
    single answer to guess). Same review shape as `review_questions`."""
    duplicates = await duplicate_checks(
        [str(q.get("question") or "") for q in questions], existing or []
    )
    reviews = []
    for index, (question, duplicate) in enumerate(zip(questions, duplicates, strict=True)):
        rules = written_rule_issues(question)
        issues = list(rules)
        if not duplicate["passed"]:
            issues.append("It is almost the same as an existing question.")
        reviews.append(
            {
                "index": index,
                "question_id": question.get("id"),
                "passed": not issues,
                "verdict": "accept" if not issues else "reject",
                "issues": issues,
                "checks": {"rules": {"passed": not rules, "issues": rules}, "duplicate": duplicate},
            }
        )
    return reviews


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    reviews = await review_questions(
        list(payload.get("questions") or []), list(payload.get("existing") or [])
    )
    return {
        "reviews": reviews,
        "passed": sum(1 for r in reviews if r["passed"]),
        "rejected": sum(1 for r in reviews if not r["passed"]),
        "prompt_version": PROMPT_ID,
    }
