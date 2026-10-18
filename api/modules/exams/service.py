"""Business logic for the exams module. Owner: Udith.

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
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import jobs
from api.core.ai_client import AIClient
from api.core.config import get_settings
from api.core.errors import AppError, ForbiddenError, NotFoundError
from api.core.security import CurrentUser
from api.modules.exams import repository
from api.modules.exams.schemas import (
    EvaluateResponse,
    ModuleStatus,
    PaperGenerateRequest,
    PaperOut,
    QuestionResult,
    StudentQuestion,
    SubmitRequest,
    TopicScore,
)
from api.modules.questions import service as questions_service
from api.modules.syllabus import service as syllabus_service
from shared.enums import JobStatus, JobType

logger = logging.getLogger(__name__)

MODULE_NAME = "exams"
LETTERS = "ABCDE"
WEAK_THRESHOLD = 60.0  # topics below this percent are marked weak
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
    weak_topics = [s.topic for s in by_topic if s.percent < WEAK_THRESHOLD]
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


async def generate_paper(
    session: AsyncSession, user: CurrentUser, req: PaperGenerateRequest, ai: AIClient
) -> PaperOut:
    """Generate an AI model paper for the chosen topics and save it for this student."""
    topics = await syllabus_service.get_topics(session, req.topic_ids)
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


# --------------------------------------------------------------------------- submit


async def submit_paper(
    session: AsyncSession,
    user: CurrentUser,
    paper_id: uuid.UUID,
    req: SubmitRequest,
    ai: AIClient,
) -> EvaluateResponse:
    """Mark the answers, explain the wrong ones, and save the attempt."""
    paper = await repository.get_paper(session, paper_id)
    if paper is None:
        raise NotFoundError(f"Paper '{paper_id}' not found", code="PAPER_NOT_FOUND")
    if paper.paper_type == "ai_generated" and paper.created_by != user.id and not user.is_admin:
        raise ForbiddenError("This paper belongs to another student")

    rows = await repository.get_grading_rows(session, paper_id)
    questions = [
        GradingQuestion(r.question_id, r.topic, r.question, r.options, r.correct_answer, r.marks)
        for r in rows
    ]
    chosen = {a.question_id: a.selected for a in req.answers}
    result = evaluate_paper(paper_id, questions, chosen)

    if req.explain:
        await _add_explanations(result, ai)

    # One `responses` row per question (the selected option is stored by id).
    option_ids = {r.question_id: dict(zip(r.options, r.option_ids, strict=True)) for r in rows}
    responses = [
        {
            "question_id": res.question_id,
            "selected_option_id": option_ids[res.question_id].get(res.selected_option or ""),
            "is_correct": res.is_correct,
            "marks_awarded": float(res.marks_awarded),
        }
        for res in result.results
    ]
    attempt = await repository.save_attempt(
        session,
        paper_id=paper_id,
        user_id=user.id,
        score=float(result.marks_obtained),
        responses=responses,
    )
    await session.commit()
    result.attempt_id = attempt.id

    # TODO(Udith + Keshomigha): call performance.service.record_mistake(...) for wrong answers
    #   and update concept mastery once the performance module exists.
    return result


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
