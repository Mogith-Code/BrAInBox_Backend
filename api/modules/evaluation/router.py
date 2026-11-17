"""HTTP endpoints for the evaluation module.

    GET    /api/v1/evaluations/questions        Structured / essay questions I can practise
    POST   /api/v1/evaluations/pages            Upload photos of a handwritten answer
    POST   /api/v1/evaluations/ocr              Read the photos -> 202 + job (OCR_ANSWER)
    POST   /api/v1/evaluations                  Mark a typed (or corrected) answer -> 202 + job
    GET    /api/v1/evaluations                  My evaluations, newest first
    GET    /api/v1/evaluations/{id}             Points covered / partial / missing, marks, tips
    GET    /api/v1/admin/evaluations            Marked answers (admin, for the accuracy report)
    PATCH  /api/v1/admin/evaluations/{id}       Enter a teacher's marks
    GET    /api/v1/admin/evaluations/accuracy   Estimated vs manual marks

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, File, UploadFile, status

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.pagination import Page, PageParamsDep
from api.core.security import AdminUserDep, CurrentUserDep
from api.modules.evaluation import service
from api.modules.evaluation.schemas import (
    AccuracyReport,
    AdminEvaluationOut,
    AnswerPagesOut,
    EvaluationBrief,
    EvaluationJobOut,
    EvaluationOut,
    EvaluationRequest,
    ManualMarksIn,
    OcrRequest,
    WrittenQuestionOut,
)

router = APIRouter(tags=["Evaluation"])


@router.get(
    "/evaluations/questions",
    response_model=Page[WrittenQuestionOut],
    summary="Structured and essay questions that can be checked",
)
async def list_questions(
    user: CurrentUserDep,
    session: SessionDep,
    paging: PageParamsDep,
    question_type: Literal["structured", "essay"] | None = None,
    unit: str | None = None,
    topic: str | None = None,
    year: int | None = None,
    hide_outdated: bool = False,
) -> Page[WrittenQuestionOut]:
    """Approved questions with an approved marking scheme. Past-paper questions on removed
    topics have `is_outdated: true`; pass `hide_outdated=true` to leave them out."""
    return await service.list_questions(
        session,
        user,
        paging,
        question_type=question_type,
        unit=unit,
        topic=topic,
        year=year,
        hide_outdated=hide_outdated,
    )


@router.post(
    "/evaluations/pages",
    response_model=AnswerPagesOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload photos of a handwritten answer",
)
async def upload_pages(
    user: CurrentUserDep,
    files: Annotated[list[UploadFile], File(description="1-6 photos: JPG, PNG or WebP")],
) -> AnswerPagesOut:
    """The photos are re-encoded and stored privately under the student's own folder. Send the
    returned `image_paths` to `POST /evaluations/ocr`."""
    return await service.upload_pages(user, files)


@router.post(
    "/evaluations/ocr",
    response_model=EvaluationJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Read a handwritten answer (OCR)",
)
async def start_ocr(
    req: OcrRequest,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
) -> EvaluationJobOut:
    """Poll `GET /jobs/{job_id}`; then `GET /evaluations/{evaluation_id}` has `status:
    "ocr_ready"` and the recognised `ocr_text`. Let the student correct it and send it to
    `POST /evaluations` with the same `evaluation_id`."""
    return await service.start_ocr(session, user, req, ai, background_tasks)


@router.post(
    "/evaluations",
    response_model=EvaluationJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Check a structured or essay answer",
)
async def create_evaluation(
    req: EvaluationRequest,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
) -> EvaluationJobOut:
    """Marks the answer against the question's marking points in the background.

    Errors: 404 `QUESTION_NOT_FOUND` · 422 `NO_MARKING_SCHEME` · 429 `DAILY_LIMIT_REACHED`."""
    return await service.create_evaluation(session, user, req, ai, background_tasks)


@router.get(
    "/evaluations", response_model=Page[EvaluationBrief], summary="My checked answers, newest first"
)
async def list_evaluations(
    user: CurrentUserDep,
    session: SessionDep,
    paging: PageParamsDep,
    question_id: uuid.UUID | None = None,
) -> Page[EvaluationBrief]:
    return await service.list_evaluations(session, user, paging, question_id)


@router.get(
    "/evaluations/{evaluation_id}",
    response_model=EvaluationOut,
    summary="Result of one checked answer",
)
async def get_evaluation(
    evaluation_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> EvaluationOut:
    """Formative feedback, never an official mark (see `disclaimer`). The model answer is only
    included once the answer is marked."""
    return await service.get_evaluation(session, user, evaluation_id)


# --------------------------------------------------------------------------- admin
admin = APIRouter(prefix="/admin/evaluations", tags=["Admin: evaluation accuracy"])


@admin.get("/accuracy", response_model=AccuracyReport, summary="Estimated vs manual marks")
async def accuracy(admin_user: AdminUserDep, session: SessionDep) -> AccuracyReport:
    return await service.admin_accuracy(session)


@admin.get("", response_model=Page[AdminEvaluationOut], summary="Marked answers")
async def admin_list(
    admin_user: AdminUserDep,
    session: SessionDep,
    paging: PageParamsDep,
    only_manual: bool = False,
) -> Page[AdminEvaluationOut]:
    return await service.admin_list(session, paging, only_manual)


@admin.patch(
    "/{evaluation_id}", response_model=AdminEvaluationOut, summary="Enter a teacher's marks"
)
async def set_manual_marks(
    evaluation_id: uuid.UUID, req: ManualMarksIn, admin_user: AdminUserDep, session: SessionDep
) -> AdminEvaluationOut:
    return await service.admin_set_manual_marks(
        session, admin_user, evaluation_id, req.manual_marks
    )


router.include_router(admin)
