"""Business logic for the exams module. Owner: Udith.

Student side:
  * GET /papers, GET /papers/{id}: approved past papers (and the student's own model papers);
    every question says whether it is on an outdated part of the syllabus.
  * POST /papers/generate: a model paper from a blueprint (units / topics, how many MCQ /
    structured / essay questions, difficulty mix, time limit). Unseen approved bank questions
    are used first; only the gaps go to the AI (BUILD_PAPER job, queued: 202 + job id). The
    ai_service regenerates a rejected question once and then drops it.
  * POST /papers/{id}/submit: MCQs are marked at once; structured / essay answers are marked in
    the background by the evaluation module, and the attempt's score is completed when they are.
  * PAPERS_DAILY_LIMIT: papers a student may generate per 24 hours (all generate routes).

Paper generation + evaluation are ported from Udith's original code:
  * `evaluate_paper` / `option_from_letter` = his `app/services/evaluator.py` (unchanged logic)
  * `generate_paper` = his `/exam/generate-paper` route; the AI part now runs in the ai_service
    (BUILD_PAPER job) and the questions are stored in the database
  * explanations = his `explainer.py`, now the ai_service `/sync/explain-mcq` call

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock, jobs
from api.core.ai_client import AIClient
from api.core.config import get_settings
from api.core.errors import (
    AppError,
    ForbiddenError,
    NotFoundError,
    TooManyRequestsError,
)
from api.core.pagination import Page, PageParams
from api.core.security import CurrentUser
from api.modules.evaluation import service as evaluation_service
from api.modules.exams import repository
from api.modules.exams.schemas import (
    DifficultyMix,
    EvaluateResponse,
    ModuleStatus,
    PaperBlueprint,
    PaperDetail,
    PaperGenerateRequest,
    PaperJobOut,
    PaperOption,
    PaperOut,
    PaperQuestionOut,
    PaperSummary,
    QuestionResult,
    StudentQuestion,
    SubmitRequest,
    TopicScore,
    UnitPaperGenerateRequest,
    WrittenResult,
)
from api.modules.jobs import service as jobs_service
from api.modules.knowledge_base import service as knowledge_service
from api.modules.performance import service as performance_service
from api.modules.questions import service as questions_service
from api.modules.syllabus import service as syllabus_service
from shared.db.models import AIJob, Paper
from shared.enums import (
    ContentStatus,
    Difficulty,
    JobStatus,
    JobType,
    MasterySource,
    PaperKind,
    QuestionType,
)

logger = logging.getLogger(__name__)

MODULE_NAME = "exams"
LETTERS = "ABCDE"
EXAMPLES_PER_TOPIC = 3


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# --------------------------------------------------------------------------- marking


@dataclass
class GradingQuestion:
    id: uuid.UUID
    topic: str
    question: str
    options: list[str]
    correct_answer: str
    marks: int = 1


def option_from_letter(q: GradingQuestion, letter: str | None) -> str | None:
    """ "B" -> text of the 2nd option. Anything invalid counts as not answered."""
    if not letter:
        return None
    first = letter.strip().upper()[:1]
    if not first:
        return None
    idx = LETTERS.find(first)
    if idx == -1 or idx >= len(q.options):
        return None
    return q.options[idx]


def evaluate_paper(
    paper_id: uuid.UUID,
    questions: list[GradingQuestion],
    chosen: dict[uuid.UUID, str | None],
) -> EvaluateResponse:
    """Mark every question, then score per topic. Pure function: no database, no AI."""
    results: list[QuestionResult] = []
    topic_stats: dict[str, list[int]] = {}  # topic -> [correct, total]
    answered = correct = marks_obtained = marks_total = 0

    for q in questions:
        selected = option_from_letter(q, chosen.get(q.id))
        is_correct = selected is not None and selected == q.correct_answer

        if selected is not None:
            answered += 1
        if is_correct:
            correct += 1
            marks_obtained += q.marks
        marks_total += q.marks

        stats = topic_stats.setdefault(q.topic, [0, 0])
        stats[1] += 1
        if is_correct:
            stats[0] += 1

        results.append(
            QuestionResult(
                question_id=q.id,
                topic=q.topic,
                question=q.question,
                selected_option=selected,
                correct_answer=q.correct_answer,
                is_correct=is_correct,
                marks_awarded=q.marks if is_correct else 0,
            )
        )

    by_topic = [
        TopicScore(topic=t, correct=c, total=n, percent=round(100 * c / n, 1))
        for t, (c, n) in topic_stats.items()
    ]
    # Weak = grade S or F; the thresholds live in performance/grading.py.
    weak_topics = [
        s.topic for s in by_topic if performance_service.is_weak_topic_percent(s.percent)
    ]
    percent = round(100 * marks_obtained / marks_total, 1) if marks_total else 0.0

    return EvaluateResponse(
        paper_id=paper_id,
        total_questions=len(questions),
        answered=answered,
        correct=correct,
        marks_obtained=marks_obtained,
        marks_total=marks_total,
        percent=percent,
        by_topic=by_topic,
        weak_topics=weak_topics,
        results=results,
    )


# --------------------------------------------------------------------------- generate


def _show_answers() -> bool:
    settings = get_settings()
    return settings.DEBUG_SHOW_ANSWERS and settings.ENVIRONMENT != "prod"


async def check_papers_limit(session: AsyncSession, user: CurrentUser) -> None:
    """429 DAILY_LIMIT_REACHED after PAPERS_DAILY_LIMIT papers in 24 hours (0 = no limit).

    Every BUILD_PAPER job counts (blueprint, topic and unit papers), except failed ones.
    Admins have no limit."""
    limit = get_settings().PAPERS_DAILY_LIMIT
    if limit <= 0 or user.is_admin:
        return
    since = clock.now() - timedelta(hours=24)
    used = await jobs_service.count_recent_jobs(session, user.id, JobType.BUILD_PAPER, since)
    if used >= limit:
        raise TooManyRequestsError(
            f"You have made {limit} papers in the last 24 hours. Try again tomorrow.",
            code="DAILY_LIMIT_REACHED",
        )


async def generate_paper(
    session: AsyncSession, user: CurrentUser, req: PaperGenerateRequest, ai: AIClient
) -> PaperOut:
    """Generate an AI model paper for the chosen topics and save it for this student.

    Synchronous; used by the old `/exam/generate-paper` URL only."""
    topics = await syllabus_service.get_topics(session, req.topic_ids)
    await check_papers_limit(session, user)
    payload = {
        "num_questions": req.num_questions,
        "topics": [
            {
                "topic_id": str(t.id),
                "title": t.title,
                "unit_id": str(t.unit_id),
                "examples": await questions_service.get_example_questions(
                    session, t.id, EXAMPLES_PER_TOPIC
                ),
            }
            for t in topics
        ],
    }

    # The student waits for the paper, so the job runs inline (the ai_jobs row keeps a record).
    # TODO(Udith): switch to enqueue_job + polling GET /jobs/{id} if generation gets slow.
    job = await jobs.create_job(session, JobType.BUILD_PAPER, payload, requested_by=user.id)
    job = await jobs.run_job_inline(session, job, ai)
    if job.status != JobStatus.SUCCEEDED or not job.result:
        raise AppError(
            "The AI service could not generate the paper. Please try again.",
            code="AI_GENERATION_FAILED",
            status_code=502,
        )

    output: dict[str, Any] = job.result.get("result", {})
    warnings: list[str] = output.get("warnings", [])
    if not output.get("questions"):
        raise AppError(
            f"Could not generate any questions. {' '.join(warnings)}".strip(),
            code="NO_QUESTIONS_GENERATED",
            status_code=502,
        )

    title = req.title or "Model paper: " + ", ".join(t.title for t in topics)
    paper, saved = await repository.save_generated_paper(
        session,
        title=title[:200],
        user_id=user.id,
        questions=output["questions"],
        prompt_version=output.get("prompt_version"),
    )
    await session.commit()

    topic_titles = {t.id: t.title for t in topics}
    show = _show_answers()
    return PaperOut(
        paper_id=paper.id,
        title=paper.title,
        total_questions=len(saved),
        questions=[
            StudentQuestion(
                id=q.id,
                topic_id=q.topic_id,
                topic=topic_titles.get(q.topic_id, "General") if q.topic_id else "General",
                question=q.question,
                options=q.options,
                marks=q.marks,
                correct_answer=q.correct_answer if show else None,
            )
            for q in saved
        ],
        warnings=warnings,
    )


async def generate_paper_by_units(
    session: AsyncSession, user: CurrentUser, req: UnitPaperGenerateRequest, ai: AIClient
) -> PaperOut:
    """Generate an AI model paper for the chosen units (1..10) and save it for this student."""
    unit_numbers = sorted(set(req.unit_numbers))
    if any(u < 1 or u > 10 for u in unit_numbers):
        raise AppError(
            "Unit numbers must be between 1 and 10", code="INVALID_UNITS", status_code=422
        )
    if req.num_questions < len(unit_numbers):
        raise AppError(
            "num_questions must be at least the number of selected units",
            code="NOT_ENOUGH_QUESTIONS",
            status_code=422,
        )

    all_units = await syllabus_service.list_units(session)
    units_by_number = {u.number: u for u in all_units}
    selected_units = [units_by_number[n] for n in unit_numbers if n in units_by_number]
    if len(selected_units) != len(unit_numbers):
        missing = [str(n) for n in unit_numbers if n not in units_by_number]
        raise NotFoundError(
            f"Units not found in syllabus: {', '.join(missing)}", code="UNIT_NOT_FOUND"
        )

    await check_papers_limit(session, user)
    payload = {
        "num_questions": req.num_questions,
        "units": [
            {
                "unit_id": str(u.id),
                "unit_number": u.number,
                "title": u.title,
            }
            for u in selected_units
        ],
    }

    job = await jobs.create_job(session, JobType.BUILD_PAPER, payload, requested_by=user.id)
    job = await jobs.run_job_inline(session, job, ai)
    if job.status != JobStatus.SUCCEEDED or not job.result:
        raise AppError(
            "The AI service could not generate the paper. Please try again.",
            code="AI_GENERATION_FAILED",
            status_code=502,
        )

    output: dict[str, Any] = job.result.get("result", {})
    warnings: list[str] = output.get("warnings", [])
    if not output.get("questions"):
        raise AppError(
            f"Could not generate any questions. {' '.join(warnings)}".strip(),
            code="NO_QUESTIONS_GENERATED",
            status_code=502,
        )

    title = req.title or "Model paper: Units " + ", ".join(str(n) for n in unit_numbers)
    paper, saved = await repository.save_generated_paper(
        session,
        title=title[:200],
        user_id=user.id,
        questions=output["questions"],
        prompt_version=output.get("prompt_version"),
    )
    await session.commit()

    show = _show_answers()
    # Unit questions have no topic, so label each one with its unit ("Unit 6: Genetics").
    # `saved` is in the same order as output["questions"].
    unit_titles = {str(u.id): f"Unit {u.number}: {u.title}" for u in selected_units}
    return PaperOut(
        paper_id=paper.id,
        title=paper.title,
        total_questions=len(saved),
        questions=[
            StudentQuestion(
                id=q.id,
                topic_id=q.topic_id,
                topic=unit_titles.get(str(item.get("unit_id")), "General"),
                question=q.question,
                options=q.options,
                marks=q.marks,
                correct_answer=q.correct_answer if show else None,
            )
            for q, item in zip(saved, output["questions"], strict=True)
        ],
        warnings=warnings,
    )


# --------------------------------------------------------------------------- submit


async def submit_paper(
    session: AsyncSession,
    user: CurrentUser,
    paper_id: uuid.UUID,
    req: SubmitRequest,
    ai: AIClient,
    background_tasks: BackgroundTasks | None = None,
) -> EvaluateResponse:
    """Mark the MCQs, explain the wrong ones, save the attempt, and queue the marking of the
    structured / essay answers (evaluation module). The attempt is "submitted" until those are
    marked, then "graded" with the full score (see `on_paper_answer_marked`)."""
    paper = await repository.get_paper(session, paper_id)
    if paper is None:
        raise NotFoundError(f"Paper '{paper_id}' not found", code="PAPER_NOT_FOUND")
    if paper.paper_type == "ai_generated" and paper.created_by != user.id and not user.is_admin:
        raise ForbiddenError("This paper belongs to another student")

    rows = await repository.get_grading_rows(session, paper_id)
    mcq_rows = [r for r in rows if r.question_type == QuestionType.MCQ]
    written_rows = [r for r in rows if r.question_type != QuestionType.MCQ]
    questions = [
        GradingQuestion(r.question_id, r.topic, r.question, r.options, r.correct_answer, r.marks)
        for r in mcq_rows
    ]
    chosen = {a.question_id: a.selected for a in req.answers}
    texts = {a.question_id: (a.answer_text or "").strip() for a in req.answers}
    result = evaluate_paper(paper_id, questions, chosen)

    if req.explain:
        await _add_explanations(result, ai)

    # One `responses` row per question (the selected option is stored by id).
    option_ids = {r.question_id: dict(zip(r.options, r.option_ids, strict=True)) for r in mcq_rows}
    responses: list[dict[str, Any]] = [
        {
            "question_id": res.question_id,
            "selected_option_id": option_ids[res.question_id].get(res.selected_option or ""),
            "is_correct": res.is_correct,
            "marks_awarded": float(res.marks_awarded),
        }
        for res in result.results
    ]
    written: list[tuple[Any, uuid.UUID, str]] = []
    for row in written_rows:
        text, response_id = texts.get(row.question_id, ""), uuid.uuid4()
        responses.append(
            {
                "id": response_id,
                "question_id": row.question_id,
                "answer_text": text or None,
                # Blank answers get 0 at once; the others when the evaluation finishes.
                "marks_awarded": None if text else 0.0,
            }
        )
        written.append((row, response_id, text))
    attempt = await repository.save_attempt(
        session,
        paper_id=paper_id,
        user_id=user.id,
        score=float(result.marks_obtained),
        responses=responses,
        status="submitted" if any(text for _, _, text in written) else "graded",
    )
    # Mistakes, unit + concept mastery and Learn progress, in this same commit.
    await performance_service.after_attempt_marked(
        session, user.id, attempt.id, source=MasterySource.EXAM
    )
    await performance_service.record_study_activity(session, user.id)
    await session.commit()
    result.attempt_id = attempt.id

    result.written = await _queue_written_answers(
        session, user, attempt.id, written, ai, background_tasks
    )
    result.pending_written = sum(1 for w in result.written if w.status == "queued")
    if not result.pending_written and attempt.status == "submitted":
        attempt.status = "graded"  # nothing could be marked: the MCQ score is final
        await session.commit()
    result.status = "marking" if result.pending_written else "graded"
    result.total_questions += len(written)
    result.answered += sum(1 for _, _, text in written if text)
    result.written_marks_total = sum(row.marks for row, _, _ in written)
    return result


async def _queue_written_answers(
    session: AsyncSession,
    user: CurrentUser,
    attempt_id: uuid.UUID,
    written: list[tuple[Any, uuid.UUID, str]],
    ai: AIClient,
    background_tasks: BackgroundTasks | None,
) -> list[WrittenResult]:
    out = []
    for row, response_id, text in written:
        base = {
            "question_id": row.question_id,
            "topic": row.topic,
            "question": row.question,
            "question_type": row.question_type.value,
            "max_marks": row.marks,
        }
        if not text:
            out.append(WrittenResult(**base, status="unanswered"))
            continue
        job = await evaluation_service.start_paper_answer_evaluation(
            session, user.id, row.question_id, text, response_id=response_id, attempt_id=attempt_id
        )
        if job is None:
            out.append(WrittenResult(**base, status="not_markable"))
            continue
        if background_tasks is not None:
            jobs.enqueue_job(job, background_tasks, ai)
        out.append(
            WrittenResult(
                **base,
                status="queued",
                evaluation_id=uuid.UUID(str(job.input["evaluation_id"])),
                job_id=job.id,
            )
        )
    return out


async def on_paper_answer_marked(session: AsyncSession, job: AIJob) -> None:
    """Job listener: when a written answer of an exam attempt is marked (or failed), store its
    marks on the response and update the attempt's score; when it was the last one, the attempt
    is "graded". A failed evaluation counts as 0 marks."""
    if job.job_type != JobType.EVALUATE_ANSWER:
        return
    attempt_id = _uuid_or_none(job.input.get("attempt_id"))
    response_id = _uuid_or_none(job.input.get("response_id"))
    if attempt_id is None or response_id is None:
        return  # an answer checked on its own (POST /evaluations)
    attempt = await repository.get_attempt(session, attempt_id)
    response = await repository.get_response(session, response_id)
    if attempt is None or response is None:
        return
    if job.status == JobStatus.SUCCEEDED:
        result = (job.result or {}).get("result") or {}
        max_marks = float(job.input.get("max_marks") or 0)
        marks = float(result.get("estimated_marks") or 0)
        response.marks_awarded = round(min(marks, max_marks) if max_marks else marks, 2)
    responses = await repository.attempt_responses(session, attempt.id)
    written_ids = [r.id for r in responses if r.answer_text]
    still_open = await evaluation_service.open_paper_evaluations(
        session, written_ids, exclude_id=_uuid_or_none(job.input.get("evaluation_id"))
    )
    attempt.score = round(sum(float(r.marks_awarded or 0) for r in responses), 2)
    if still_open == 0:
        attempt.status = "graded"


def _uuid_or_none(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


async def _add_explanations(result: EvaluateResponse, ai: AIClient) -> None:
    """Ask the ai_service to explain every wrong / unanswered question. Never fails the request."""
    wrong = [r for r in result.results if not r.is_correct]
    if not wrong:
        return
    items = [
        {
            "question_id": str(r.question_id),
            "question": r.question,
            "correct_answer": r.correct_answer,
            "selected_option": r.selected_option,
        }
        for r in wrong
    ]
    try:
        response = await ai.sync("explain-mcq", {"items": items})
    except AppError as exc:
        logger.warning("Explanations skipped: %s", exc.message)
        return
    explanations: dict[str, str] = response.get("result", {}).get("explanations", {})
    for r in wrong:
        r.explanation = explanations.get(str(r.question_id))


# --------------------------------------------------------------------------- view papers


async def _visible_paper(session: AsyncSession, user: CurrentUser, paper_id: uuid.UUID) -> Paper:
    """An approved past paper (anyone), or a paper the student made (or any paper, for admins).
    Anything else is a 404, so other students' papers aren't leaked."""
    paper = await repository.get_paper(session, paper_id)
    if paper is not None:
        public = (
            paper.paper_type == PaperKind.PAST_PAPER.value
            and paper.status == ContentStatus.APPROVED
        )
        if public or paper.created_by == user.id or user.is_admin:
            return paper
    raise NotFoundError(f"Paper '{paper_id}' not found", code="PAPER_NOT_FOUND")


async def list_papers(
    session: AsyncSession,
    *,
    year: int | None,
    question_type: QuestionType | None,
    paging: PageParams,
) -> Page[PaperSummary]:
    """GET /papers: approved past papers, newest year first."""
    rows, total = await repository.list_past_papers(
        session, year=year, question_type=question_type, offset=paging.offset, limit=paging.size
    )
    items = [
        PaperSummary(
            id=r.paper.id,
            title=r.paper.title,
            paper_type=r.paper.paper_type,
            year=r.paper.year,
            question_types=r.question_types,
            question_count=r.question_count,
            outdated_count=r.outdated_count,
            total_marks=r.paper.total_marks,
            duration_minutes=r.paper.duration_minutes,
        )
        for r in rows
    ]
    return Page.create(items, total, paging)


async def get_paper_detail(
    session: AsyncSession, user: CurrentUser, paper_id: uuid.UUID, *, hide_outdated: bool = False
) -> PaperDetail:
    """GET /papers/{id}: the questions without answers. `hide_outdated` leaves out questions on
    an outdated part of the syllabus (they still count in `question_count`)."""
    paper = await _visible_paper(session, user, paper_id)
    rows = await repository.paper_questions(session, paper.id)
    shown = [r for r in rows if not (hide_outdated and r.is_outdated)]
    return PaperDetail(
        id=paper.id,
        title=paper.title,
        paper_type=paper.paper_type,
        year=paper.year,
        duration_minutes=paper.duration_minutes,
        total_marks=paper.total_marks,
        question_count=len(rows),
        hidden_outdated=len(rows) - len(shown),
        questions=[
            PaperQuestionOut(
                id=r.question.id,
                position=r.position,
                question_type=r.question.question_type.value,
                topic_id=r.question.topic_id,
                topic=r.topic_title or "General",
                stem=r.question.stem,
                marks=r.marks,
                options=[PaperOption(label=o.label, text=o.text) for o in r.options],
                is_outdated=r.is_outdated,
            )
            for r in shown
        ],
    )


# --------------------------------------------------------------------------- model paper blueprint
DIFFICULTIES = (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD)
TYPE_COUNTS = (
    (QuestionType.MCQ, "mcq_count"),
    (QuestionType.STRUCTURED, "structured_count"),
    (QuestionType.ESSAY, "essay_count"),
)
# Written bank questions are only usable with a marking scheme, so look at a few more.
WRITTEN_CANDIDATES = 4


def split_by_mix(count: int, mix: DifficultyMix) -> dict[Difficulty, int]:
    """Share `count` questions by the difficulty mix (largest remainder), e.g. 10 with
    0.3 / 0.5 / 0.2 -> easy 3, medium 5, hard 2. Pure."""
    weights = {Difficulty.EASY: mix.easy, Difficulty.MEDIUM: mix.medium, Difficulty.HARD: mix.hard}
    total = sum(weights.values())
    exact = {d: count * w / total for d, w in weights.items()}
    out = {d: int(v) for d, v in exact.items()}
    left = count - sum(out.values())
    for d in sorted(DIFFICULTIES, key=lambda d: (-(exact[d] - out[d]), DIFFICULTIES.index(d))):
        if left <= 0:
            break
        out[d] += 1
        left -= 1
    return out


@dataclass
class Target:
    """Where generated questions go: a topic, or a whole unit."""

    title: str
    unit_id: uuid.UUID
    topic_id: uuid.UUID | None = None


def plan_gaps(
    missing: dict[tuple[QuestionType, Difficulty], int], targets: list[Target]
) -> list[dict[str, Any]]:
    """Spread every missing (type, difficulty) count over the targets as evenly as possible.
    The first target to get an extra question moves on each time, so small counts don't all
    land on the first unit. Pure."""
    gaps: list[dict[str, Any]] = []
    if not targets:
        return gaps
    start = 0
    for (kind, difficulty), count in missing.items():
        if count <= 0:
            continue
        base, extra = divmod(count, len(targets))
        for i in range(len(targets)):
            n = base + (1 if (i - start) % len(targets) < extra else 0)
            if n <= 0:
                continue
            target = targets[i]
            gaps.append(
                {
                    "question_type": kind.value,
                    "difficulty": difficulty.value,
                    "count": n,
                    "title": target.title,
                    "unit_id": str(target.unit_id),
                    "topic_id": str(target.topic_id) if target.topic_id else None,
                }
            )
        start = (start + extra) % len(targets)
    return gaps


async def _scope(
    session: AsyncSession, req: PaperBlueprint
) -> tuple[list[Target], list[uuid.UUID], list[uuid.UUID]]:
    """(targets, unit ids, topic ids). 404 TOPIC_NOT_FOUND / UNIT_NOT_FOUND."""
    topics = await syllabus_service.get_topics(session, req.topic_ids) if req.topic_ids else []
    units = []
    if req.unit_numbers:
        by_number = {u.number: u for u in await syllabus_service.list_units(session)}
        missing = [str(n) for n in req.unit_numbers if n not in by_number]
        if missing:
            raise NotFoundError(
                f"Units not found in syllabus: {', '.join(missing)}", code="UNIT_NOT_FOUND"
            )
        units = [by_number[n] for n in dict.fromkeys(req.unit_numbers)]
    if topics:
        targets = [Target(t.title, t.unit_id, t.id) for t in topics]
    else:
        targets = [Target(u.title, u.id) for u in units]
    unit_ids = list(dict.fromkeys([t.unit_id for t in topics] + [u.id for u in units]))
    return targets, unit_ids, [t.id for t in topics]


async def start_model_paper(
    session: AsyncSession,
    user: CurrentUser,
    req: PaperBlueprint,
    ai: AIClient,
    background_tasks: BackgroundTasks,
) -> PaperJobOut:
    """POST /papers/generate: take unseen approved bank questions for every (type, difficulty)
    slot of the blueprint, then queue ONE BUILD_PAPER job for the gaps. The paper is saved when
    the job succeeds (`on_paper_built`).

    404 TOPIC_NOT_FOUND / UNIT_NOT_FOUND · 429 DAILY_LIMIT_REACHED."""
    targets, unit_ids, topic_ids = await _scope(session, req)
    await check_papers_limit(session, user)

    picked: list[uuid.UUID] = []
    missing: dict[tuple[QuestionType, Difficulty], int] = {}
    for kind, field in TYPE_COUNTS:
        wanted = int(getattr(req, field))
        if wanted <= 0:
            continue
        for difficulty, n in split_by_mix(wanted, req.difficulty).items():
            if n <= 0:
                continue
            ids = await questions_service.pick_unseen_bank_questions(
                session,
                user.id,
                question_type=kind,
                difficulty=difficulty,
                unit_ids=unit_ids,
                topic_ids=topic_ids,
                limit=n if kind == QuestionType.MCQ else n * WRITTEN_CANDIDATES,
                exclude=set(picked),
            )
            if kind != QuestionType.MCQ:  # an answer can only be marked with a scheme
                markable = await knowledge_service.questions_with_marking_scheme(session, ids)
                ids = [i for i in ids if i in markable]
            ids = ids[:n]
            picked.extend(ids)
            if len(ids) < n:
                missing[(kind, difficulty)] = n - len(ids)

    gaps = plan_gaps(missing, targets)
    title = req.title or "Model paper: " + ", ".join(t.title for t in targets)
    payload = {
        "gaps": gaps,
        "existing": await questions_service.question_stems(session, picked),
        # Read by on_paper_built only (the ai_service ignores them):
        "bank_question_ids": [str(i) for i in picked],
        "title": title[:200],
        "time_limit_minutes": req.time_limit_minutes,
        "unit_ids": [str(i) for i in unit_ids],
        "blueprint": req.model_dump(mode="json", exclude={"num_questions"}),
    }
    job = await jobs.create_job(session, JobType.BUILD_PAPER, payload, requested_by=user.id)
    jobs.enqueue_job(job, background_tasks, ai)
    return PaperJobOut(
        job_id=job.id, from_bank=len(picked), to_generate=sum(g["count"] for g in gaps)
    )


async def on_paper_built(session: AsyncSession, job: AIJob) -> None:
    """BUILD_PAPER of a blueprint finished: save the paper (bank questions + the generated ones,
    written ones with their AI marking scheme) in the job's commit. The job result becomes
    {paper_id, title, total_questions, from_bank, generated, warnings}.

    Topic / unit papers (no "gaps" in the input) are saved by the request itself."""
    if job.input.get("gaps") is None or job.requested_by is None:
        return
    output: dict[str, Any] = (job.result or {}).get("result") or {}
    warnings = [str(w) for w in output.get("warnings") or []]
    bank_ids = [
        i for i in (_uuid_or_none(x) for x in job.input.get("bank_question_ids") or []) if i
    ]
    bank = await repository.questions_by_id(session, bank_ids)
    questions = [bank[i] for i in bank_ids if i in bank]
    generated = 0
    for item in output.get("questions") or []:
        try:
            question = await repository.add_generated_question(
                session, item, user_id=job.requested_by, job_id=job.id
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("Skipped a malformed generated question in job %s", job.id)
            continue
        if question.question_type != QuestionType.MCQ:
            await knowledge_service.save_ai_marking_scheme(
                session,
                question.id,
                str(item.get("model_answer") or ""),
                list(item.get("points") or []),
            )
        questions.append(question)
        generated += 1
    if not questions:
        raise AppError(
            f"Could not make any questions for this paper. {' '.join(warnings)}".strip(),
            code="NO_QUESTIONS_GENERATED",
            status_code=502,
        )
    paper = await repository.save_blueprint_paper(
        session,
        title=str(job.input.get("title") or "Model paper")[:200],
        user_id=job.requested_by,
        questions=questions,
        blueprint=dict(job.input.get("blueprint") or {}),
        unit_ids=[i for i in (_uuid_or_none(x) for x in job.input.get("unit_ids") or []) if i],
        duration_minutes=job.input.get("time_limit_minutes"),
        job_id=job.id,
    )
    job.result = {
        **(job.result or {}),
        "result": {
            "paper_id": str(paper.id),
            "title": paper.title,
            "total_questions": len(questions),
            "from_bank": len(questions) - generated,
            "generated": generated,
            "warnings": warnings,
        },
    }


jobs.register_job_handler(JobType.BUILD_PAPER, on_paper_built)
jobs.register_job_listener(on_paper_answer_marked)
