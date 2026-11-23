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
import math
import random
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.core.ai_client import AIClient
from api.core.errors import AppError, ConflictError, NotFoundError
from api.modules.performance import service as performance_service
from api.modules.profiles import service as profiles_service
from api.modules.quality import service as quality_service
from api.modules.quizzes import repository
from api.modules.quizzes.repository import McqRow, QuizRow
from api.modules.quizzes.schemas import (
    AnswerFeedback,
    AnswerSavedOut,
    ConceptRef,
    DiagnosticQuestionOut,
    DiagnosticResult,
    DiagnosticStartOut,
    MasteryChange,
    MisconceptionCard,
    MisconceptionCount,
    ModuleStatus,
    OptionOut,
    PracticeHub,
    QuizAnswerIn,
    QuizBrief,
    QuizCreate,
    QuizOut,
    QuizQuestionOut,
    QuizResult,
    ReviewItem,
    TopicAccuracy,
    UnitRef,
    UnitResult,
)
from api.modules.syllabus import service as syllabus_service
from api.modules.syllabus.service import UnitInfo
from shared.db.models import Attempt, MCQOption, Response
from shared.enums import MasterySource

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

    1 per unit that has questions; then each extra question goes to the unit furthest below
    its fair share (total x weight / sum of weights) that still has unused questions.
    A unit with no approved questions is left out, so one empty unit can't block every student.
    Raises AppError NOT_ENOUGH_QUESTIONS when the whole bank has fewer than `total` questions.
    """
    usable = [u for u in units if available.get(u.id, 0) > 0]
    if sum(available.get(u.id, 0) for u in usable) < total:
        missing = [u for u in units if u not in usable]
        names = ", ".join(f"Unit {u.number}" for u in missing)
        detail = f" No approved questions yet for: {names}." if names else ""
        raise ConflictError(
            f"The question bank needs at least {total} approved MCQs." + detail,
            code="NOT_ENOUGH_QUESTIONS",
        )
    weight_sum = sum(u.exam_weight for u in usable) or 1.0
    allocation = {u.id: 1 for u in usable}
    for _ in range(total - len(usable)):
        candidates = [u for u in usable if allocation[u.id] < available[u.id]]
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
        if unit.id in allocation  # a unit with no approved questions is left out
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
    await profiles_service.check_achievements(
        session, user_id, only=profiles_service.ACTIVITY_ACHIEVEMENTS
    )
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
    units_not_checked: list[UnitRef]


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
        # Units the test could not measure, so the app never presents them as measured.
        units_not_checked=[
            UnitRef(unit_code=u.code, unit_title=u.title)
            for u in sorted(units.values(), key=lambda u: u.number)
            if u.id not in asked
        ],
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
    await performance_service.refresh_topic_progress(session, user_id)
    await profiles_service.check_achievements(session, user_id)
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
        units_not_checked=marked.units_not_checked,
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


# =========================================================================== quizzes (practice)
# Flow: POST /quizzes -> POST /quizzes/{id}/responses (instant feedback, one per question)
#       -> POST /quizzes/{id}/submit -> GET /quizzes/{id}/result
#
# Every answer goes through performance_service.record_answer(): it updates the concept's
# mastery, records a typed mistake and checks for a recurring misconception. The feedback
# card is built from the MCQ mapping (option -> misconception), so no AI is called here.

SECONDS_PER_QUESTION = 90  # timed quizzes: 1.5 minutes per MCQ
RECENT_QUIZZES = 5
MISTAKE_POOL = 200


def quiz_minutes(count: int) -> int:
    return max(1, math.ceil(count * SECONDS_PER_QUESTION / 60))


def _resolve_unit(units: list[UnitInfo], ref: str) -> UnitInfo:
    """A unit by UUID, code ("u6") or number ("6"). 404 UNIT_NOT_FOUND."""
    wanted = ref.strip().lower()
    for unit in units:
        if wanted in (str(unit.id), f"u{unit.number}", str(unit.number)):
            return unit
    raise NotFoundError(f"Unit '{ref}' not found", code="UNIT_NOT_FOUND")


def pick_questions(
    candidates: list[QuizRow],
    count: int,
    *,
    seen: set[uuid.UUID],
    weakness: dict[uuid.UUID, float] | None = None,
    rng: random.Random | None = None,
) -> list[QuizRow]:
    """Pure: choose `count` questions. Unseen questions come first; with `weakness`
    ({question_id: mastery of its weakest concept}) the weakest concepts come first of all."""
    rng = rng or random.Random()
    pool = list(candidates)
    rng.shuffle(pool)  # random order inside each group
    if weakness is not None:
        pool.sort(key=lambda q: (round(weakness.get(q.id, 0.5), 2), q.id in seen))
    else:
        pool.sort(key=lambda q: q.id in seen)
    return pool[:count]


def _quiz_question_out(
    position: int, row: QuizRow, unit: UnitInfo, response: Response | None, finished: bool
) -> QuizQuestionOut:
    answered = response is not None and response.selected_option_id is not None
    correct = row.correct_option
    return QuizQuestionOut(
        id=row.id,
        position=position,
        stem=row.stem,
        unit_code=unit.code,
        unit_title=unit.title,
        topic_id=row.topic_id,
        topic_title=row.topic_title,
        difficulty=row.difficulty,
        options=[OptionOut(id=o.id, label=o.label, text=o.text) for o in row.options],
        selected_option_id=response.selected_option_id if response else None,
        # The solution is only sent for questions that are answered (or after submitting).
        correct_option_id=correct.id if correct and (answered or finished) else None,
        is_correct=response.is_correct if response and (answered or finished) else None,
        flagged=bool(response.flagged) if response else False,
    )


async def _quiz_out(session: AsyncSession, attempt: Attempt) -> QuizOut:
    units = {u.id: u for u in await syllabus_service.list_units(session)}
    rows = await repository.quiz_questions(session, list(attempt.question_ids))
    responses = await repository.get_responses(session, attempt.id)
    paper = await repository.get_paper(session, attempt.paper_id)
    finished = attempt.status != "in_progress"
    return QuizOut(
        quiz_id=attempt.id,
        title=paper.title if paper else "Quiz",
        status=attempt.status,
        total=len(rows),
        answered=sum(1 for r in responses.values() if r.selected_option_id is not None),
        timed=attempt.time_limit_minutes is not None,
        time_limit_minutes=attempt.time_limit_minutes,
        started_at=attempt.started_at,
        questions=[
            _quiz_question_out(n, row, units[row.unit_id], responses.get(row.id), finished)
            for n, row in enumerate(rows, start=1)
        ],
    )


async def start_quiz(session: AsyncSession, user_id: uuid.UUID, req: QuizCreate) -> QuizOut:
    """Pick the questions and freeze them. 404 UNIT_NOT_FOUND / TOPIC_NOT_FOUND ·
    422 NO_QUESTIONS when nothing approved matches."""
    units = await syllabus_service.list_units(session)
    unit = _resolve_unit(units, req.unit) if req.unit else None
    topic = await syllabus_service.resolve_topic(session, req.topic) if req.topic else None

    mistake_ids = None
    if req.mistakes_only:
        mistake_ids = await performance_service.mistake_question_ids(session, user_id, MISTAKE_POOL)
        if not mistake_ids:
            raise AppError(
                "You have no open mistakes to practise. Nice work!",
                code="NO_MISTAKES",
                status_code=422,
            )
    candidates = [
        q
        for q in await repository.quiz_candidates(
            session,
            unit_id=unit.id if unit and topic is None else None,
            topic_id=topic.id if topic else None,
            concept_id=req.concept_id,
            question_ids=mistake_ids,
            difficulty=None if req.difficulty == "mixed" else req.difficulty,
        )
        if len(q.options) >= 2 and q.correct_option is not None
    ]
    if not candidates:
        raise AppError(
            "There are no approved questions for this selection yet. Try another topic or "
            "difficulty.",
            code="NO_QUESTIONS",
            status_code=422,
        )

    weakness = None
    if req.focus_weak:
        links = await repository.concept_links(session, [q.id for q in candidates])
        mastery = await performance_service.concept_mastery_values(
            session, user_id, list({c for ids in links.values() for c in ids})
        )
        weakness = {
            q.id: min((mastery.get(c, 0.5) for c in links.get(q.id, [])), default=0.5)
            for q in candidates
        }
    seen = await repository.seen_question_ids(session, user_id)
    chosen = pick_questions(candidates, req.count, seen=seen, weakness=weakness)

    if req.mistakes_only:
        title = "Practice my mistakes"
    elif topic is not None:
        title = f"Quiz: {topic.title}"
    elif unit is not None:
        title = f"Quiz: Unit {unit.number} {unit.title}"
    elif req.focus_weak:
        title = "Targeted practice: weak areas"
    else:
        title = "Mixed quiz"
    attempt = await repository.create_quiz(
        session,
        user_id,
        [q.id for q in chosen],
        title=title,
        unit_id=unit.id if unit else (topic.unit_id if topic else None),
        topic_id=topic.id if topic else None,
        minutes=quiz_minutes(len(chosen)) if req.timed else None,
        blueprint=req.model_dump(mode="json"),
    )
    await session.commit()
    return await _quiz_out(session, attempt)


async def _own_quiz(session: AsyncSession, user_id: uuid.UUID, quiz_id: uuid.UUID) -> Attempt:
    attempt = await repository.get_quiz_attempt(session, quiz_id)
    if attempt is None or attempt.user_id != user_id:  # someone else's = "not found"
        raise NotFoundError("Quiz not found", code="QUIZ_NOT_FOUND")
    return attempt


async def get_quiz(session: AsyncSession, user_id: uuid.UUID, quiz_id: uuid.UUID) -> QuizOut:
    return await _quiz_out(session, await _own_quiz(session, user_id, quiz_id))


async def answer_quiz_question(
    session: AsyncSession, user_id: uuid.UUID, quiz_id: uuid.UUID, req: QuizAnswerIn
) -> AnswerFeedback:
    """Save one answer and return the feedback card. Answers are final (409 ALREADY_ANSWERED),
    because the feedback shows the solution."""
    attempt = await _own_quiz(session, user_id, quiz_id)
    if attempt.status != "in_progress":
        raise ConflictError("This quiz is already submitted", code="QUIZ_FINISHED")
    if req.question_id not in attempt.question_ids:
        raise AppError("That question is not part of this quiz", code="QUESTION_NOT_IN_QUIZ")
    row = (await repository.quiz_questions(session, [req.question_id]))[0]
    chosen = next((o for o in row.options if o.id == req.option_id), None)
    correct = row.correct_option
    if chosen is None or correct is None:
        raise AppError("That option does not belong to the question", code="OPTION_INVALID")

    responses = await repository.get_responses(session, attempt.id)
    response = responses.get(row.id)
    if response is not None and response.selected_option_id is not None:
        raise ConflictError("You already answered this question", code="ALREADY_ANSWERED")
    if response is None:
        response = Response(attempt_id=attempt.id, question_id=row.id)
        await repository.add_response(session, response)
        responses[row.id] = response
    response.selected_option_id = chosen.id
    response.is_correct = chosen.id == correct.id
    response.marks_awarded = 1.0 if response.is_correct else 0.0
    response.time_spent_seconds = req.time_spent_seconds
    response.answered_at = clock.now()
    await session.flush()

    effect = await performance_service.record_answer(
        session,
        user_id,
        question_id=row.id,
        score=1.0 if response.is_correct else 0.0,
        response_id=response.id,
        misconception_id=None if response.is_correct else chosen.misconception_id,
    )
    await quality_service.record_answer(
        session, row.id, correct=bool(response.is_correct), label=chosen.label
    )
    await performance_service.record_study_activity(session, user_id)
    await profiles_service.check_achievements(
        session, user_id, only=profiles_service.ACTIVITY_ACHIEVEMENTS
    )
    if req.time_spent_seconds:
        await performance_service.add_study_time(session, user_id, req.time_spent_seconds)

    misconception = None
    if not response.is_correct and chosen.misconception_id is not None:
        found = await repository.get_misconceptions(session, [chosen.misconception_id])
        m = found.get(chosen.misconception_id)
        if m is not None:
            misconception = MisconceptionCard(
                id=m.id, title=m.title, description=m.description, correction=m.correction_md
            )
    concept = None
    if effect.concept_id is not None:
        briefs = await performance_service.concept_briefs(session, [effect.concept_id])
        if briefs:
            c = briefs[0]
            concept = ConceptRef(
                id=c.id, name=c.name, topic_id=c.topic_id, topic_title=c.topic_title
            )
    mastery = None
    if effect.mastery_after is not None:
        mastery = MasteryChange(
            before=round(effect.mastery_before * 100)
            if effect.mastery_before is not None
            else None,
            after=round(effect.mastery_after * 100),
            level=effect.level,
        )
    await session.commit()
    return AnswerFeedback(
        question_id=row.id,
        selected_option_id=chosen.id,
        correct_option_id=correct.id,
        is_correct=bool(response.is_correct),
        explanation=row.explanation,
        option_explanation=chosen.explanation_md,
        misconception=misconception,
        concept=concept,
        mastery=mastery,
        mistake_type=effect.mistake_type.value if effect.mistake_type else None,
        recurring_misconception=effect.recurring,
        recurring_count=effect.recurring_count,
        answered=sum(1 for r in responses.values() if r.selected_option_id is not None),
        total=len(attempt.question_ids),
    )


async def flag_quiz_question(
    session: AsyncSession,
    user_id: uuid.UUID,
    quiz_id: uuid.UUID,
    question_id: uuid.UUID,
    flagged: bool,
) -> None:
    """Flag a question for review (kept with the response, so it survives app restarts)."""
    attempt = await _own_quiz(session, user_id, quiz_id)
    if question_id not in attempt.question_ids:
        raise AppError("That question is not part of this quiz", code="QUESTION_NOT_IN_QUIZ")
    responses = await repository.get_responses(session, attempt.id)
    response = responses.get(question_id)
    if response is None:
        response = Response(attempt_id=attempt.id, question_id=question_id)
        await repository.add_response(session, response)
    response.flagged = flagged
    await session.commit()


def _label(option: MCQOption | None) -> str | None:
    return f"{option.label}. {option.text}" if option else None


def build_quiz_result(
    attempt: Attempt,
    title: str,
    rows: list[QuizRow],
    responses: dict[uuid.UUID, Response],
    misconceptions: dict[uuid.UUID, Any],
) -> QuizResult:
    """Pure: the result screen from the stored answers. Unanswered questions count as wrong."""
    by_topic: dict[uuid.UUID, TopicAccuracy] = {}
    counts: dict[uuid.UUID, int] = {}
    review = []
    score = answered = seconds = 0
    for position, row in enumerate(rows, start=1):
        response = responses.get(row.id)
        selected = next(
            (o for o in row.options if response and o.id == response.selected_option_id), None
        )
        is_correct = bool(response and response.is_correct)
        score += int(is_correct)
        answered += int(selected is not None)
        seconds += (response.time_spent_seconds or 0) if response else 0
        topic = by_topic.setdefault(
            row.topic_id,
            TopicAccuracy(
                topic_id=row.topic_id, topic=row.topic_title, correct=0, total=0, percent=0
            ),
        )
        topic.total += 1
        topic.correct += int(is_correct)
        if selected is not None and not is_correct and selected.misconception_id in misconceptions:
            counts[selected.misconception_id] = counts.get(selected.misconception_id, 0) + 1
        review.append(
            ReviewItem(
                question_id=row.id,
                position=position,
                stem=row.stem,
                topic=row.topic_title,
                selected=_label(selected),
                correct=_label(row.correct_option) or "",
                is_correct=is_correct,
                explanation=row.explanation,
                flagged=bool(response.flagged) if response else False,
            )
        )
    for topic in by_topic.values():
        topic.percent = round(100 * topic.correct / topic.total) if topic.total else 0
    if not seconds and attempt.submitted_at is not None:
        seconds = max(0, int((attempt.submitted_at - attempt.started_at).total_seconds()))
    total = len(rows)
    return QuizResult(
        quiz_id=attempt.id,
        title=title,
        score=score,
        total=total,
        answered=answered,
        percent=round(100 * score / total) if total else 0,
        time_seconds=seconds,
        by_topic=sorted(by_topic.values(), key=lambda t: (t.percent, t.topic)),
        misconceptions=[
            MisconceptionCount(
                id=mid,
                title=misconceptions[mid].title,
                correction=misconceptions[mid].correction_md,
                count=n,
            )
            for mid, n in sorted(counts.items(), key=lambda item: -item[1])
        ],
        review=review,
        mistakes=answered - score,
        disclaimer=DISCLAIMER,
    )


async def _quiz_result(session: AsyncSession, attempt: Attempt) -> QuizResult:
    rows = await repository.quiz_questions(session, list(attempt.question_ids))
    responses = await repository.get_responses(session, attempt.id)
    paper = await repository.get_paper(session, attempt.paper_id)
    misconception_ids = list(
        {o.misconception_id for row in rows for o in row.options if o.misconception_id}
    )
    misconceptions = await repository.get_misconceptions(session, misconception_ids)
    return build_quiz_result(
        attempt, paper.title if paper else "Quiz", rows, responses, misconceptions
    )


async def submit_quiz(session: AsyncSession, user_id: uuid.UUID, quiz_id: uuid.UUID) -> QuizResult:
    """Finish the quiz: unanswered questions are stored as wrong, unit mastery gets a new
    snapshot and the recommendations are refreshed. Submitting twice returns the same result."""
    attempt = await _own_quiz(session, user_id, quiz_id)
    if attempt.status == "in_progress":
        rows = await repository.quiz_questions(session, list(attempt.question_ids))
        responses = await repository.get_responses(session, attempt.id)
        score = 0
        for row in rows:
            response = responses.get(row.id)
            if response is None:
                response = Response(attempt_id=attempt.id, question_id=row.id)
                await repository.add_response(session, response)
            if response.selected_option_id is None:
                response.is_correct = False
                response.marks_awarded = 0.0
            score += int(bool(response.is_correct))
        attempt.status = "graded"
        attempt.submitted_at = clock.now()
        attempt.score = float(score)
        attempt.max_score = float(len(rows))
        attempt.percentage = round(100 * score / len(rows), 1) if rows else 0.0
        # Concept mastery was updated answer by answer; here only units / mistakes / progress.
        await performance_service.after_attempt_marked(
            session, user_id, attempt.id, source=MasterySource.QUIZ, record_concepts=False
        )
        await profiles_service.check_achievements(session, user_id)
        await session.commit()
    return await _quiz_result(session, attempt)


async def quiz_result(session: AsyncSession, user_id: uuid.UUID, quiz_id: uuid.UUID) -> QuizResult:
    attempt = await _own_quiz(session, user_id, quiz_id)
    if attempt.status == "in_progress":
        raise ConflictError("This quiz is not submitted yet", code="QUIZ_NOT_FINISHED")
    return await _quiz_result(session, attempt)


def _brief(attempt: Attempt, title: str) -> QuizBrief:
    return QuizBrief(
        quiz_id=attempt.id,
        title=title,
        status=attempt.status,
        total=len(attempt.question_ids),
        score=int(attempt.score) if attempt.score is not None else None,
        percent=round(attempt.percentage) if attempt.percentage is not None else None,
        started_at=attempt.started_at,
    )


async def practice_hub(session: AsyncSession, user_id: uuid.UUID) -> PracticeHub:
    quizzes = await repository.recent_quizzes(session, user_id, RECENT_QUIZZES + 5)
    in_progress = next((_brief(a, t) for a, t in quizzes if a.status == "in_progress"), None)
    mastery = await performance_service.concept_mastery_values(session, user_id)
    mistakes = await performance_service.mistake_question_ids(session, user_id, MISTAKE_POOL)
    return PracticeHub(
        in_progress=in_progress,
        recent=[_brief(a, t) for a, t in quizzes if a.status != "in_progress"][:RECENT_QUIZZES],
        open_mistakes=len(mistakes),
        weak_concepts=sum(
            1 for value in mastery.values() if value < performance_service.WEAK_BELOW
        ),
        approved_questions=len(await repository.quiz_candidates(session)),
    )
