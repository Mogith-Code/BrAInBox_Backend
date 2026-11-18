"""Business logic for the evaluation module: formative feedback on structured / essay answers.

Flow (typed):        POST /evaluations                 -> 202 {evaluation_id, job_id}
Flow (handwritten):  POST /evaluations/pages           -> photos stored (re-encoded)
                     POST /evaluations/ocr             -> 202, OCR_ANSWER job
                     GET  /evaluations/{id}            -> status "ocr_ready" with the text
                     POST /evaluations (evaluation_id) -> 202, EVALUATE_ANSWER job
Both end with        GET  /evaluations/{id}            -> covered / partial / missing points,
                                                          estimated marks, model answer, tips

The marks are computed in the ai_service from keyword and semantic matches per marking point;
the LLM only writes tips. When the job succeeds this module stores the result, moves the
concept's mastery and records one mistake per missing / partly covered point, all in the same
commit as the job's "succeeded".

Rules:
  * SQL lives in `repository.py`, not here.
  * The marking scheme comes from knowledge_base.service (never its repository).
  * AI work goes through `api.core.jobs`, never directly to a provider.
"""

import io
import logging
import math
import uuid
from datetime import timedelta
from typing import Any

from fastapi import BackgroundTasks, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock, jobs, storage
from api.core.ai_client import AIClient
from api.core.config import get_settings
from api.core.errors import AppError, ConflictError, NotFoundError, TooManyRequestsError
from api.core.pagination import Page, PageParams
from api.core.security import CurrentUser
from api.modules.evaluation import repository
from api.modules.evaluation.schemas import (
    AccuracyReport,
    AdminEvaluationOut,
    AnswerPagesOut,
    EvaluationBrief,
    EvaluationJobOut,
    EvaluationOut,
    EvaluationRequest,
    OcrRequest,
    PointResult,
    WrittenQuestionOut,
)
from api.modules.jobs.service import readable_error
from api.modules.knowledge_base import service as knowledge_service
from api.modules.performance import service as performance_service
from api.modules.syllabus import service as syllabus_service
from shared.db.models import AIJob, Evaluation, Question
from shared.enums import EvaluationMethod, JobStatus, JobType, MistakeType, QuestionType

logger = logging.getLogger(__name__)

MODULE_NAME = "evaluation"
IMAGE_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
MAX_IMAGE_SIDE = 2200  # pixels; enough for handwriting, small enough for OCR limits
MAX_MISTAKES_PER_ANSWER = 6
# How the scorer's "problem" of a marking point maps to a mistake type:
#   missing_concept   -> a key concept is missing             (knowledge_gap)
#   wrong_application -> right terms, wrong use               (conceptual)
#   incomplete        -> the point is only partly made        (incomplete)
PROBLEM_TYPES = {
    "missing_concept": MistakeType.KNOWLEDGE_GAP,
    "wrong_application": MistakeType.CONCEPTUAL,
    "incomplete": MistakeType.INCOMPLETE,
}


def question_code(question: Question) -> str:
    return f"Q-{question.number}"


# =========================================================================== questions to practise


async def list_questions(
    session: AsyncSession,
    user: CurrentUser,
    paging: PageParams,
    *,
    question_type: str | None,
    unit: str | None,
    topic: str | None,
    year: int | None,
    hide_outdated: bool,
) -> Page[WrittenQuestionOut]:
    unit_id = None
    if unit:
        units = await syllabus_service.list_units(session)
        wanted = unit.strip().lower()
        match = next(
            (u for u in units if wanted in (str(u.id), f"u{u.number}", str(u.number))), None
        )
        if match is None:
            raise NotFoundError(f"Unit '{unit}' not found", code="UNIT_NOT_FOUND")
        unit_id = match.id
    topic_id = (await syllabus_service.resolve_topic(session, topic)).id if topic else None
    rows, total = await repository.list_written_questions(
        session,
        question_type=question_type,
        unit_id=unit_id,
        topic_id=topic_id,
        year=year,
        hide_outdated=hide_outdated,
        offset=paging.offset,
        limit=paging.size,
    )
    stats = await repository.my_question_stats(session, user.id, [q.id for q, _, _ in rows])
    items = [
        WrittenQuestionOut(
            id=q.id,
            code=question_code(q),
            question_type=q.question_type.value,  # type: ignore[arg-type]
            stem=q.stem,
            marks=float(q.marks),
            difficulty=q.difficulty.value,
            year=q.year,
            is_outdated=q.is_outdated,
            topic_id=q.topic_id,
            topic_title=topic_title,
            unit_number=unit_number,
            my_attempts=stats.get(q.id, (0, None))[0],
            my_best_marks=stats.get(q.id, (0, None))[1],
        )
        for q, topic_title, unit_number in rows
    ]
    return Page.create(items, total, paging)


async def _written_question(session: AsyncSession, question_id: uuid.UUID) -> Question:
    question = await repository.get_question(session, question_id)
    if (
        question is None
        or question.status.value != "approved"
        or question.question_type == QuestionType.MCQ
    ):
        raise NotFoundError("Question not found", code="QUESTION_NOT_FOUND")
    return question


# =========================================================================== photos of handwriting


def reencode_image(data: bytes) -> bytes:
    """Decode and re-save the picture as a plain JPEG (blocking: use run_in_threadpool).

    Re-encoding drops everything that is not pixels (EXIF location, embedded scripts, files
    that only pretend to be images) and shrinks very large photos."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)  # keep the page the right way up
        image = image.convert("RGB")
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=85, optimize=True)
        return out.getvalue()


async def upload_pages(user: CurrentUser, files: list[UploadFile]) -> AnswerPagesOut:
    """Store the photos of a handwritten answer under answers/{user_id}/{upload_id}/.

    Errors: 422 NO_PAGES / TOO_MANY_PAGES / UNSUPPORTED_IMAGE / INVALID_IMAGE · 413 IMAGE_TOO_LARGE.
    """
    settings = get_settings()
    if not files:
        raise AppError("Add at least one photo of your answer.", code="NO_PAGES", status_code=422)
    if len(files) > settings.ANSWER_MAX_PAGES:
        raise AppError(
            f"You can upload at most {settings.ANSWER_MAX_PAGES} pages for one answer.",
            code="TOO_MANY_PAGES",
            status_code=422,
        )
    max_bytes = settings.ANSWER_IMAGE_MAX_MB * 1024 * 1024
    upload_id = uuid.uuid4()
    paths = []
    for number, file in enumerate(files, start=1):
        if (file.content_type or "").lower() not in IMAGE_TYPES:
            raise AppError(
                "Photos must be JPG, PNG or WebP.", code="UNSUPPORTED_IMAGE", status_code=422
            )
        data = await file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise AppError(
                f"Page {number} is larger than {settings.ANSWER_IMAGE_MAX_MB} MB.",
                code="IMAGE_TOO_LARGE",
                status_code=413,
            )
        try:
            clean = await run_in_threadpool(reencode_image, data)
        except Exception as exc:
            raise AppError(
                f"Page {number} is not a readable picture.", code="INVALID_IMAGE", status_code=422
            ) from exc
        path = f"answers/{user.id}/{upload_id}/page-{number}.jpg"
        await run_in_threadpool(storage.upload_bytes, path, clean, "image/jpeg")
        paths.append(path)
    return AnswerPagesOut(image_paths=paths, pages=len(paths))


# =========================================================================== start OCR / evaluation


async def _check_daily_limit(
    session: AsyncSession, user: CurrentUser, *, handwritten: bool = False
) -> None:
    settings = get_settings()
    limit = settings.OCR_DAILY_LIMIT_PER_USER if handwritten else settings.EVALUATIONS_DAILY_LIMIT
    if limit <= 0 or user.is_admin:
        return
    used = await repository.count_since(
        session, user.id, clock.now() - timedelta(hours=24), handwritten=handwritten
    )
    if used >= limit:
        what = "handwritten answers" if handwritten else "answers"
        raise TooManyRequestsError(
            f"You have checked {limit} {what} in the last 24 hours. Try again tomorrow.",
            code="DAILY_LIMIT_REACHED",
        )


async def start_ocr(
    session: AsyncSession,
    user: CurrentUser,
    req: OcrRequest,
    ai: AIClient,
    background_tasks: BackgroundTasks,
) -> EvaluationJobOut:
    """Queue OCR for the uploaded pages. The pages must be the student's own uploads."""
    await _written_question(session, req.question_id)
    own_folder = f"answers/{user.id}/"
    if any(not p.startswith(own_folder) or ".." in p for p in req.image_paths):
        raise AppError(
            "Those pages are not your uploads.", code="INVALID_IMAGE_PATH", status_code=422
        )
    await _check_daily_limit(session, user, handwritten=True)
    evaluation = Evaluation(
        user_id=user.id,
        question_id=req.question_id,
        answer_image_path=req.image_paths[0],
        status=JobStatus.QUEUED,
    )
    await repository.add(session, evaluation)
    job = await jobs.create_job(
        session,
        JobType.OCR_ANSWER,
        {"evaluation_id": str(evaluation.id), "image_paths": req.image_paths},
        requested_by=user.id,
    )
    evaluation.job_id = job.id
    await session.commit()
    jobs.enqueue_job(job, background_tasks, ai)
    return EvaluationJobOut(evaluation_id=evaluation.id, job_id=job.id, status="queued")


async def create_evaluation(
    session: AsyncSession,
    user: CurrentUser,
    req: EvaluationRequest,
    ai: AIClient,
    background_tasks: BackgroundTasks,
) -> EvaluationJobOut:
    """Queue the marking of an answer. 404 QUESTION_NOT_FOUND / EVALUATION_NOT_FOUND ·
    409 EVALUATION_BUSY · 422 NO_MARKING_SCHEME · 429 DAILY_LIMIT_REACHED."""
    question = await _written_question(session, req.question_id)
    scheme = await knowledge_service.get_marking_scheme(session, question.id)
    if scheme is None:
        raise AppError(
            "This question has no approved marking scheme yet, so it can't be checked.",
            code="NO_MARKING_SCHEME",
            status_code=422,
        )
    answer = req.answer_text.strip()
    if req.evaluation_id is not None:  # the corrected text of a handwritten answer
        evaluation = await _own_evaluation(session, user, req.evaluation_id)
        if evaluation.question_id != question.id:
            raise AppError("That evaluation is for another question.", code="QUESTION_MISMATCH")
        if evaluation.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            raise ConflictError("This answer is still being processed", code="EVALUATION_BUSY")
        if evaluation.estimated_marks is not None:
            raise ConflictError("This answer is already marked", code="ALREADY_EVALUATED")
    else:
        await _check_daily_limit(session, user)
        evaluation = Evaluation(user_id=user.id, question_id=question.id)
        await repository.add(session, evaluation)
    evaluation.answer_text = answer
    evaluation.status = JobStatus.QUEUED
    evaluation.max_marks = min(float(question.marks), scheme.total_marks) or scheme.total_marks
    job = await jobs.create_job(
        session,
        JobType.EVALUATE_ANSWER,
        _evaluation_payload(evaluation, question, answer, scheme),
        requested_by=user.id,
    )
    evaluation.job_id = job.id
    await session.commit()
    jobs.enqueue_job(job, background_tasks, ai)
    return EvaluationJobOut(evaluation_id=evaluation.id, job_id=job.id, status="queued")


def _evaluation_payload(
    evaluation: Evaluation, question: Question, answer: str, scheme: Any
) -> dict[str, Any]:
    """EVALUATE_ANSWER payload (ai_service/pipelines/evaluation/scorer.py)."""
    return {
        "evaluation_id": str(evaluation.id),
        "question": question.stem,
        "answer_text": answer,
        "max_marks": evaluation.max_marks,
        "topic_id": str(question.topic_id) if question.topic_id else None,
        "points": [
            {
                "id": str(p.id),
                "text": p.text,
                "marks": p.marks,
                "is_required": p.is_required,
                "keywords": p.keywords,
            }
            for p in scheme.points
        ],
    }


async def start_paper_answer_evaluation(
    session: AsyncSession,
    user_id: uuid.UUID,
    question_id: uuid.UUID,
    answer_text: str,
    *,
    response_id: uuid.UUID,
    attempt_id: uuid.UUID,
) -> AIJob | None:
    """Queue the marking of a written answer on an exam paper (exams module).

    Unlike POST /evaluations the question may be one of the student's own AI questions (not
    approved yet): its AI-made marking scheme is used then. No daily limit (papers have their
    own, PAPERS_DAILY_LIMIT). Returns the job to enqueue (create_job commits), or None when the
    question has no marking scheme at all."""
    question = await repository.get_question(session, question_id)
    if question is None or question.question_type == QuestionType.MCQ:
        return None
    scheme = await knowledge_service.get_marking_scheme(session, question.id, allow_ai_draft=True)
    if scheme is None:
        return None
    answer = answer_text.strip()
    evaluation = Evaluation(
        user_id=user_id,
        question_id=question.id,
        response_id=response_id,
        answer_text=answer,
        status=JobStatus.QUEUED,
        max_marks=min(float(question.marks), scheme.total_marks) or scheme.total_marks,
    )
    await repository.add(session, evaluation)
    payload = _evaluation_payload(evaluation, question, answer, scheme)
    payload.update({"attempt_id": str(attempt_id), "response_id": str(response_id)})
    job = await jobs.create_job(session, JobType.EVALUATE_ANSWER, payload, requested_by=user_id)
    evaluation.job_id = job.id
    await session.commit()
    return job


async def open_paper_evaluations(
    session: AsyncSession, response_ids: list[uuid.UUID], exclude_id: uuid.UUID | None = None
) -> int:
    """How many evaluations of these exam responses are still queued / running."""
    return await repository.count_open_for_responses(session, response_ids, exclude_id)


# =========================================================================== job handlers
# Registered at the bottom of this file; run by api/core/jobs.py in the job's own commit.


async def _job_evaluation(session: AsyncSession, job: AIJob) -> Evaluation | None:
    try:
        evaluation_id = uuid.UUID(str(job.input.get("evaluation_id")))
    except (ValueError, TypeError):
        return None
    return await repository.get_evaluation(session, evaluation_id)


async def on_ocr_done(session: AsyncSession, job: AIJob) -> None:
    evaluation = await _job_evaluation(session, job)
    if evaluation is None:
        return
    result = (job.result or {}).get("result", {})
    evaluation.ocr_text = str(result.get("ocr_text") or "")
    # Not marked yet: the student checks the text first. See `_status` ("ocr_ready").
    evaluation.status = JobStatus.SUCCEEDED


def problems_from(
    points: list[dict[str, Any]], structure: dict[str, Any]
) -> list[tuple[MistakeType, str]]:
    """Pure: the mistakes of one marked answer, the most valuable missing points first."""
    not_covered = sorted(
        (p for p in points if p.get("status") != "covered"),
        key=lambda p: (not p.get("is_required"), -float(p.get("marks") or 0)),
    )
    problems = [
        (PROBLEM_TYPES.get(str(p.get("problem")), MistakeType.KNOWLEDGE_GAP), str(p.get("text")))
        for p in not_covered[:MAX_MISTAKES_PER_ANSWER]
    ]
    covered = sum(1 for p in points if p.get("status") != "missing")
    if covered >= 2 and structure.get("in_order") is False:
        # The ideas are there but not in a logical order: an answer-structure mistake.
        problems.append((MistakeType.INCOMPLETE, "Answer structure: put your points in order."))
    return problems


async def on_evaluated(session: AsyncSession, job: AIJob) -> None:
    evaluation = await _job_evaluation(session, job)
    if evaluation is None:
        return
    result: dict[str, Any] = (job.result or {}).get("result", {})
    points: list[dict[str, Any]] = list(result.get("points") or [])
    max_marks = float(result.get("max_marks") or evaluation.max_marks or 0)
    estimated = min(float(result.get("estimated_marks") or 0), max_marks)

    evaluation.method = EvaluationMethod.HYBRID
    evaluation.estimated_marks = estimated
    evaluation.max_marks = max_marks
    evaluation.keyword_coverage = result.get("keyword_coverage")  # type: ignore[assignment]
    evaluation.semantic_score = result.get("semantic_score")  # type: ignore[assignment]
    evaluation.confidence = result.get("confidence")  # type: ignore[assignment]
    evaluation.matched_points = points
    evaluation.feedback = result.get("feedback")
    evaluation.prompt_version = result.get("prompt_version")
    evaluation.model = result.get("model")
    evaluation.status = JobStatus.SUCCEEDED

    await performance_service.record_written_answer(
        session,
        evaluation.user_id,
        question_id=evaluation.question_id,
        score=estimated / max_marks if max_marks else 0.0,
        problems=problems_from(points, result.get("structure") or {}),
    )
    await performance_service.record_study_activity(session, evaluation.user_id)


async def on_job_failed(session: AsyncSession, job: AIJob) -> None:
    evaluation = await _job_evaluation(session, job)
    if evaluation is not None:
        evaluation.status = JobStatus.FAILED


# =========================================================================== read


async def _own_evaluation(
    session: AsyncSession, user: CurrentUser, evaluation_id: uuid.UUID
) -> Evaluation:
    evaluation = await repository.get_evaluation(session, evaluation_id)
    if evaluation is None or evaluation.user_id != user.id:  # someone else's = "not found"
        raise NotFoundError("Evaluation not found", code="EVALUATION_NOT_FOUND")
    return evaluation


def _status(evaluation: Evaluation) -> str:
    if evaluation.status == JobStatus.SUCCEEDED and evaluation.estimated_marks is None:
        return "ocr_ready"  # the photos were read; the answer is not marked yet
    if evaluation.status in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.SUCCEEDED):
        return evaluation.status.value
    return "failed"


def _source(evaluation: Evaluation) -> str:
    return "handwritten" if evaluation.answer_image_path else "typed"


def _point(raw: dict[str, Any]) -> PointResult:
    try:
        point_id = uuid.UUID(str(raw.get("answer_point_id")))
    except (ValueError, TypeError):
        point_id = None
    status = str(raw.get("status") or ("covered" if raw.get("matched") else "missing"))
    return PointResult(
        id=point_id,
        text=str(raw.get("text") or ""),
        marks=float(raw.get("marks") or 0),
        status=status,  # type: ignore[arg-type]
        marks_awarded=float(raw.get("marks_awarded") or 0),
        evidence=raw.get("evidence") or None,
        matched_keywords=list(raw.get("matched_keywords") or []),
        is_required=bool(raw.get("is_required")),
    )


async def get_evaluation(
    session: AsyncSession, user: CurrentUser, evaluation_id: uuid.UUID
) -> EvaluationOut:
    evaluation = await _own_evaluation(session, user, evaluation_id)
    question = await repository.get_question(session, evaluation.question_id)
    job = await repository.get_job(session, evaluation.job_id)
    status = _status(evaluation)
    marked = status == "succeeded"
    ai_result: dict[str, Any] = {}
    if marked and job is not None and job.job_type == JobType.EVALUATE_ANSWER:
        ai_result = (job.result or {}).get("result", {})
    points = [_point(p) for p in (evaluation.matched_points or [])] if marked else []
    scheme = (
        await knowledge_service.get_marking_scheme(
            session, evaluation.question_id, allow_ai_draft=evaluation.response_id is not None
        )
        if marked
        else None
    )
    error = None
    if status == "failed":
        error, _ = readable_error(job.error if job else None)
    estimated, maximum = evaluation.estimated_marks, evaluation.max_marks
    return EvaluationOut(
        id=evaluation.id,
        question_id=evaluation.question_id,
        question=question.stem if question else "",
        question_type=question.question_type.value if question else "structured",
        status=status,  # type: ignore[arg-type]
        source=_source(evaluation),  # type: ignore[arg-type]
        answer_text=evaluation.answer_text,
        ocr_text=evaluation.ocr_text,
        estimated_marks=estimated if marked else None,
        max_marks=maximum,
        percent=round(100 * estimated / maximum)
        if marked and estimated is not None and maximum
        else None,
        covered=sum(1 for p in points if p.status == "covered"),
        partial=sum(1 for p in points if p.status == "partial"),
        missing=sum(1 for p in points if p.status == "missing"),
        points=points,
        model_answer=scheme.answer_text if scheme else None,
        feedback=evaluation.feedback if marked else None,
        tips=[str(t) for t in ai_result.get("tips") or []],
        strengths=[str(t) for t in ai_result.get("strengths") or []],
        tips_ai_generated=bool(ai_result.get("ai_generated")),
        structure_ok=(ai_result.get("structure") or {}).get("ok") if ai_result else None,
        confidence=float(evaluation.confidence)
        if marked and evaluation.confidence is not None
        else None,
        error=error,
        created_at=evaluation.created_at,
    )


async def list_evaluations(
    session: AsyncSession, user: CurrentUser, paging: PageParams, question_id: uuid.UUID | None
) -> Page[EvaluationBrief]:
    rows, total = await repository.list_evaluations(
        session, user.id, question_id, paging.offset, paging.size
    )
    questions = await repository.get_questions(session, [e.question_id for e in rows])
    items = [
        EvaluationBrief(
            id=e.id,
            question_id=e.question_id,
            question=questions[e.question_id].stem if e.question_id in questions else "",
            status=_status(e),
            source=_source(e),
            estimated_marks=e.estimated_marks,
            max_marks=e.max_marks,
            created_at=e.created_at,
        )
        for e in rows
    ]
    return Page.create(items, total, paging)


# =========================================================================== admin: accuracy


def accuracy_report(pairs: list[tuple[float, float]]) -> AccuracyReport:
    """Pure: how close the estimated marks are to a teacher's marks. Used to tune the
    similarity thresholds (scripts/eval_accuracy.py prints the same numbers)."""
    note = "Estimated marks are formative feedback. Tune the thresholds with 30+ samples."
    if not pairs:
        return AccuracyReport(
            samples=0, mean_absolute_error=None, within_one_mark=None, correlation=None, note=note
        )
    errors = [abs(e - m) for e, m in pairs]
    correlation = None
    if len(pairs) >= 2:
        mean_e = sum(e for e, _ in pairs) / len(pairs)
        mean_m = sum(m for _, m in pairs) / len(pairs)
        cov = sum((e - mean_e) * (m - mean_m) for e, m in pairs)
        spread = math.sqrt(sum((e - mean_e) ** 2 for e, _ in pairs)) * math.sqrt(
            sum((m - mean_m) ** 2 for _, m in pairs)
        )
        correlation = round(cov / spread, 3) if spread else None
    return AccuracyReport(
        samples=len(pairs),
        mean_absolute_error=round(sum(errors) / len(errors), 2),
        within_one_mark=round(sum(1 for err in errors if err <= 1.0) / len(errors), 3),
        correlation=correlation,
        note=note,
    )


async def admin_accuracy(session: AsyncSession) -> AccuracyReport:
    return accuracy_report(await repository.manual_pairs(session))


def _admin_out(evaluation: Evaluation, question: Question | None) -> AdminEvaluationOut:
    difference = None
    if evaluation.manual_marks is not None and evaluation.estimated_marks is not None:
        difference = round(evaluation.estimated_marks - evaluation.manual_marks, 2)
    return AdminEvaluationOut(
        id=evaluation.id,
        question=question.stem if question else "",
        answer_text=evaluation.answer_text,
        estimated_marks=evaluation.estimated_marks,
        max_marks=evaluation.max_marks,
        manual_marks=evaluation.manual_marks,
        difference=difference,
        created_at=evaluation.created_at,
    )


async def admin_list(
    session: AsyncSession, paging: PageParams, only_manual: bool
) -> Page[AdminEvaluationOut]:
    rows, total = await repository.list_marked(
        session, only_manual=only_manual, offset=paging.offset, limit=paging.size
    )
    questions = await repository.get_questions(session, [e.question_id for e in rows])
    return Page.create([_admin_out(e, questions.get(e.question_id)) for e in rows], total, paging)


async def admin_set_manual_marks(
    session: AsyncSession, admin: CurrentUser, evaluation_id: uuid.UUID, marks: float
) -> AdminEvaluationOut:
    evaluation = await repository.get_evaluation(session, evaluation_id)
    if evaluation is None or evaluation.estimated_marks is None:
        raise NotFoundError("Evaluation not found", code="EVALUATION_NOT_FOUND")
    if evaluation.max_marks is not None and marks > evaluation.max_marks:
        raise AppError(
            f"This question has only {evaluation.max_marks:g} marks.",
            code="MARKS_TOO_HIGH",
            status_code=422,
        )
    evaluation.manual_marks = marks
    evaluation.manual_marked_by = admin.id
    evaluation.manual_marked_at = clock.now()
    await session.commit()
    question = await repository.get_question(session, evaluation.question_id)
    return _admin_out(evaluation, question)


# =========================================================================== account delete / export
# Called by the auth module (DELETE /auth/me and GET /auth/me/export).


def answer_photos_folder(user_id: uuid.UUID) -> str:
    """Storage folder with every answer photo of one student (see upload_pages)."""
    return f"answers/{user_id}/"


async def export_user_data(session: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """The student's evaluations for the data export. Photos as Storage paths, not bytes."""
    rows = await repository.list_user_evaluations(session, user_id)
    return [
        {
            "id": e.id,
            "question_id": e.question_id,
            "answer_text": e.answer_text,
            "answer_image_path": e.answer_image_path,
            "ocr_text": e.ocr_text,
            "method": e.method,
            "estimated_marks": e.estimated_marks,
            "max_marks": e.max_marks,
            "feedback": e.feedback,
            "status": e.status,
            "created_at": e.created_at,
        }
        for e in rows
    ]


async def delete_user_data(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """Delete the student's evaluations (no commit). Returns the Storage paths to delete
    after the commit: the whole answer-photo folder (also photos never marked)."""
    await repository.delete_user_evaluations(session, user_id)
    return [answer_photos_folder(user_id)]


jobs.register_job_handler(JobType.OCR_ANSWER, on_ocr_done, on_job_failed)
jobs.register_job_handler(JobType.EVALUATE_ANSWER, on_evaluated, on_job_failed)
