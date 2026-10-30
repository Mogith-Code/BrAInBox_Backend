"""Business logic for the quizzes module. Owner: Udith.

Diagnostic test (onboarding "Let's find your starting point"):
  * 15 approved MCQs, at least 1 from every unit, the rest shared by past-paper weight
  * answers are saved one by one (progress survives app restarts)
  * on submit: mastery per unit, strongest / needs-work unit, AI summary (with a fallback)
  * unit mastery is saved through the performance module (history for the home screen)

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service, never its repository.
  * AI work goes through `api.core.ai_client`, never directly to a provider.
"""

import logging
import random
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.core.ai_client import AIClient
from api.core.errors import AppError, ConflictError, NotFoundError
from api.modules.performance import service as performance_service
from api.modules.profiles import service as profiles_service
from api.modules.quizzes import repository
from api.modules.quizzes.repository import McqRow
from api.modules.quizzes.schemas import (
    AnswerSavedOut,
    DiagnosticQuestionOut,
    DiagnosticResult,
    DiagnosticStartOut,
    ModuleStatus,
    OptionOut,
    UnitRef,
    UnitResult,
)
from api.modules.syllabus import service as syllabus_service
from api.modules.syllabus.service import UnitInfo
from shared.db.models import Attempt, Response

logger = logging.getLogger(__name__)

MODULE_NAME = "quizzes"
DIAGNOSTIC_QUESTIONS = 15
DIAGNOSTIC_MINUTES = 10
STRONG_FROM = 70  # mastery >= 70 -> "strong"
OK_FROM = 40  # 40-69 -> "ok", below -> "needs_work"
DISCLAIMER = "Formative feedback — not an official exam mark."


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


async def has_completed_diagnostic(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """True once the student has submitted a diagnostic test."""
    return await repository.has_graded_diagnostic(session, user_id)


# =========================================================================== pure helpers


def allocate_questions(
    units: list[UnitInfo], available: dict[uuid.UUID, int], total: int
) -> dict[uuid.UUID, int]:
    """How many questions to take from each unit.

    1 per unit first; then each extra question goes to the unit furthest below its fair
    share (total x weight / sum of weights) that still has unused questions.
    Raises AppError NOT_ENOUGH_QUESTIONS when the bank can't give `total` this way.
    """
    missing = [u for u in units if available.get(u.id, 0) == 0]
    if not units or missing or sum(available.get(u.id, 0) for u in units) < total:
        names = ", ".join(f"Unit {u.number}" for u in missing)
        detail = f" No approved questions yet for: {names}." if names else ""
        raise ConflictError(
            f"The question bank needs at least {total} approved MCQs covering all units." + detail,
            code="NOT_ENOUGH_QUESTIONS",
        )
    weight_sum = sum(u.exam_weight for u in units) or 1.0
    allocation = {u.id: 1 for u in units}
    for _ in range(total - len(units)):
        candidates = [u for u in units if allocation[u.id] < available[u.id]]
        best = max(
            candidates,
            key=lambda u: (total * u.exam_weight / weight_sum - allocation[u.id], -u.number),
        )
        allocation[best.id] += 1
    return allocation


def unit_mastery(correct: int, asked: int) -> int:
    """0-100, pulled towards 50 when there are few questions: (correct + 0.5) / (asked + 1)."""
    return round((correct + 0.5) / (asked + 1) * 100)


def unit_status(mastery: int) -> str:
    if mastery >= STRONG_FROM:
        return "strong"
    if mastery >= OK_FROM:
        return "ok"
    return "needs_work"


def template_summary(strongest: UnitRef, needs_work: UnitRef) -> str:
    """Used when the AI service is not available."""
    if strongest.unit_code == needs_work.unit_code:
        return "Your units are at a similar level. Follow your plan to build them up together."
    return (
        f"You did best in {strongest.unit_title}. "
        f"{needs_work.unit_title} needs the most work, so your plan starts there."
    )


# =========================================================================== start / answer


def _question_out(row: McqRow, unit: UnitInfo, selected: uuid.UUID | None) -> DiagnosticQuestionOut:
    return DiagnosticQuestionOut(
        id=row.id,
        unit_code=unit.code,
        unit_title=unit.title,
        stem=row.stem,
        options=[OptionOut(id=o.id, label=o.label, text=o.text) for o in row.options],
        selected_option_id=selected,
    )


async def _start_out(
    session: AsyncSession, attempt: Attempt, units: dict[uuid.UUID, UnitInfo]
) -> DiagnosticStartOut:
    rows = await repository.attempt_questions(session, attempt.paper_id)
    responses = await repository.get_responses(session, attempt.id)
    selected = {qid: r.selected_option_id for qid, r in responses.items()}
    return DiagnosticStartOut(
        attempt_id=attempt.id,
        total=len(rows),
        minutes=DIAGNOSTIC_MINUTES,
        answered=sum(1 for v in selected.values() if v is not None),
        questions=[_question_out(r, units[r.unit_id], selected.get(r.id)) for r in rows],
    )


async def start_diagnostic(session: AsyncSession, user_id: uuid.UUID) -> DiagnosticStartOut:
    """Return the unfinished diagnostic if there is one, otherwise pick 15 new questions."""
    units = {u.id: u for u in await syllabus_service.list_units(session)}
    unfinished = await repository.latest_diagnostic_attempt(session, user_id, "in_progress")
    if unfinished is not None:
        return await _start_out(session, unfinished, units)

    # Only well-formed MCQs: 2+ options and exactly one correct option.
    candidates = [
        q
        for q in await repository.diagnostic_candidates(session)
        if q.unit_id in units and len(q.options) >= 2 and q.correct_option_id is not None
    ]
    by_unit: dict[uuid.UUID, list[McqRow]] = {}
    for q in candidates:
        by_unit.setdefault(q.unit_id, []).append(q)
    ordered_units = sorted(units.values(), key=lambda u: u.number)
    allocation = allocate_questions(
        ordered_units, {u: len(qs) for u, qs in by_unit.items()}, DIAGNOSTIC_QUESTIONS
    )
    chosen = [
        q.id
        for unit in ordered_units  # questions are shown unit by unit
        for q in random.sample(by_unit[unit.id], allocation[unit.id])
    ]
    attempt = await repository.create_diagnostic(session, user_id, chosen, DIAGNOSTIC_MINUTES)
    await session.commit()
    return await _start_out(session, attempt, units)


async def _own_attempt(session: AsyncSession, user_id: uuid.UUID, attempt_id: uuid.UUID) -> Attempt:
    attempt = await repository.get_diagnostic_attempt(session, attempt_id)
    if attempt is None or attempt.user_id != user_id:  # someone else's = "not found"
        raise NotFoundError("Diagnostic attempt not found", code="ATTEMPT_NOT_FOUND")
    return attempt


async def save_answer(
    session: AsyncSession,
    user_id: uuid.UUID,
    attempt_id: uuid.UUID,
    question_id: uuid.UUID,
    option_id: uuid.UUID,
) -> AnswerSavedOut:
    """Save (or change) one answer. Also counts as study activity for the streak."""
    attempt = await _own_attempt(session, user_id, attempt_id)
    if attempt.status != "in_progress":
        raise ConflictError("This diagnostic is already submitted", code="ATTEMPT_FINISHED")
    rows = {r.id: r for r in await repository.attempt_questions(session, attempt.paper_id)}
    row = rows.get(question_id)
    if row is None:
        raise AppError("That question is not part of this test", code="QUESTION_NOT_IN_ATTEMPT")
    if option_id not in {o.id for o in row.options}:
        raise AppError("That option does not belong to the question", code="OPTION_INVALID")

    responses = await repository.get_responses(session, attempt.id)
    if question_id in responses:
        responses[question_id].selected_option_id = option_id
    else:
        response = Response(
            attempt_id=attempt.id, question_id=question_id, selected_option_id=option_id
        )
        await repository.add_response(session, response)
        responses[question_id] = response
    await performance_service.record_study_activity(session, user_id)
    await session.commit()
    answered = sum(1 for r in responses.values() if r.selected_option_id is not None)
    return AnswerSavedOut(answered=answered, total=len(rows))


# =========================================================================== submit / result


@dataclass
class _Marked:
    units: list[UnitResult]
    mastery_by_unit_id: dict[uuid.UUID, int]
    score: int
    total: int
    strongest: UnitRef
    needs_work: UnitRef


def _mark(
    rows: list[McqRow], responses: dict[uuid.UUID, Response], units: dict[uuid.UUID, UnitInfo]
) -> _Marked:
    """Unanswered questions count as wrong."""
    asked: dict[uuid.UUID, int] = {}
    correct: dict[uuid.UUID, int] = {}
    for row in rows:
        asked[row.unit_id] = asked.get(row.unit_id, 0) + 1
        response = responses.get(row.id)
        if response is not None and response.selected_option_id == row.correct_option_id:
            correct[row.unit_id] = correct.get(row.unit_id, 0) + 1

    ordered = sorted((units[u] for u in asked), key=lambda u: u.number)
    mastery = {u.id: unit_mastery(correct.get(u.id, 0), asked[u.id]) for u in ordered}
    results = [
        UnitResult(
            unit_code=u.code,
            unit_title=u.title,
            mastery=mastery[u.id],
            status=unit_status(mastery[u.id]),  # type: ignore[arg-type]
        )
        for u in ordered
    ]
    best = max(ordered, key=lambda u: (mastery[u.id], -u.number))
    worst = min(ordered, key=lambda u: (mastery[u.id], u.number))
    return _Marked(
        units=results,
        mastery_by_unit_id=mastery,
        score=sum(correct.values()),
        total=len(rows),
        strongest=UnitRef(unit_code=best.code, unit_title=best.title),
        needs_work=UnitRef(unit_code=worst.code, unit_title=worst.title),
    )


async def _ai_summary(ai: AIClient, marked: _Marked) -> tuple[str, bool]:
    """(summary, ai_generated). Falls back to a template if the AI service fails."""
    payload = {
        "score": marked.score,
        "total": marked.total,
        "strongest": marked.strongest.model_dump(),
        "needs_work": marked.needs_work.model_dump(),
        "units": [u.model_dump() for u in marked.units],
    }
    try:
        response = await ai.sync("diagnostic-summary", payload)
        summary = str(response.get("result", {}).get("summary", "")).strip()
        if summary:
            return summary, True
    except AppError as exc:
        logger.warning("Diagnostic summary from AI failed: %s", exc.message)
    return template_summary(marked.strongest, marked.needs_work), False


async def submit_diagnostic(
    session: AsyncSession, user_id: uuid.UUID, attempt_id: uuid.UUID, ai: AIClient
) -> DiagnosticResult:
    attempt = await _own_attempt(session, user_id, attempt_id)
    if attempt.status != "in_progress":
        raise ConflictError("This diagnostic is already submitted", code="ATTEMPT_FINISHED")

    units = {u.id: u for u in await syllabus_service.list_units(session)}
    rows = await repository.attempt_questions(session, attempt.paper_id)
    responses = await repository.get_responses(session, attempt.id)
    marked = _mark(rows, responses, units)

    # Store the outcome of every question (unanswered ones too).
    for row in rows:
        response = responses.get(row.id)
        if response is None:
            response = Response(attempt_id=attempt.id, question_id=row.id)
            await repository.add_response(session, response)
        response.is_correct = response.selected_option_id == row.correct_option_id
        response.marks_awarded = 1.0 if response.is_correct else 0.0

    summary, ai_generated = await _ai_summary(ai, marked)
    attempt.status = "graded"
    attempt.submitted_at = clock.now()
    attempt.score = float(marked.score)
    attempt.feedback = {"summary": summary, "summary_ai_generated": ai_generated}
    await performance_service.record_unit_mastery(
        session, user_id, marked.mastery_by_unit_id, source="diagnostic"
    )
    await session.commit()
    return _result(attempt, marked)


def _result(attempt: Attempt, marked: _Marked) -> DiagnosticResult:
    feedback = attempt.feedback or {}
    return DiagnosticResult(
        attempt_id=attempt.id,
        completed_at=attempt.submitted_at or clock.now(),
        score=marked.score,
        total=marked.total,
        strongest=marked.strongest,
        needs_work=marked.needs_work,
        units=marked.units,
        summary=feedback.get("summary") or template_summary(marked.strongest, marked.needs_work),
        summary_ai_generated=bool(feedback.get("summary_ai_generated", False)),
        disclaimer=DISCLAIMER,
    )


async def latest_result(session: AsyncSession, user_id: uuid.UUID) -> DiagnosticResult:
    attempt = await repository.latest_diagnostic_attempt(session, user_id, "graded")
    if attempt is None:
        raise NotFoundError("No diagnostic result yet", code="DIAGNOSTIC_NOT_FOUND")
    units = {u.id: u for u in await syllabus_service.list_units(session)}
    rows = await repository.attempt_questions(session, attempt.paper_id)
    responses = await repository.get_responses(session, attempt.id)
    return _result(attempt, _mark(rows, responses, units))


async def skip_diagnostic(session: AsyncSession, user_id: uuid.UUID) -> None:
    await profiles_service.mark_diagnostic_skipped(session, user_id)


# TODO(Udith): start_quiz / submit_responses / get_results (regular quizzes)
# TODO(Udith + Keshomigha): record mistakes per concept after quizzes and diagnostics
