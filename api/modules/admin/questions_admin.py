"""Admin routes: question bank + editor. Owner: Udith.

Mounted under /api/v1/admin/questions by `admin/router.py`, which already
requires the admin role for every route in this file.

    GET  /admin/questions                    the bank (?unit=&type=&difficulty=&status=&page=&page_size=)
    POST /admin/questions/bulk               {ids, action: approve | mark_outdated | delete} -> 204
    POST /admin/questions                    create (editor)
    GET  /admin/questions/{id}               one question with its options (editor)
    PUT  /admin/questions/{id}               save (editor)

ORDER MATTERS: every fixed path (/bulk, /quality, /past-papers...) is declared BEFORE
/{question_id}, otherwise FastAPI would try to read "bulk" as a question id.

Admin routes call the services of the owning modules (here `api.modules.questions.service`);
they do not have their own SQL.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Response, UploadFile, status

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.admin import service as admin_service
from api.modules.admin.schemas import ModuleStatus
from api.modules.quality import service as quality_service
from api.modules.quality.schemas import QualityQueueOut, ReviewDecisionIn
from api.modules.questions import service as questions_service
from api.modules.questions.schemas import (
    AdminQuestionIn,
    AdminQuestionOut,
    AdminQuestionPage,
    AdminQuestionStatus,
    BulkQuestionsIn,
    DifficultyValue,
    OptionMisconceptionIn,
    OptionMisconceptionOut,
    PaperType,
    PastPaperAnswerIn,
    PastPaperOut,
    PastPaperQuestionOut,
    QuestionKind,
)

router = APIRouter(prefix="/questions", tags=["Admin: questions"])


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    return ModuleStatus(module="questions_admin", status="todo")


# ---------------------------------------------------------------- question bank


@router.get("", response_model=AdminQuestionPage, summary="Question bank")
async def list_questions(
    admin: CurrentUserDep,
    session: SessionDep,
    unit: Annotated[int | None, Query(ge=1, description="Unit number")] = None,
    type: QuestionKind | None = None,  # noqa: A002 (the app's query name)
    difficulty: DifficultyValue | None = None,
    status: AdminQuestionStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminQuestionPage:
    """Newest first. `status=outdated` shows the ones marked outdated. Without `status`,
    archived questions (deleted but already answered by students) are left out.
    `past_paper_percent` = share of past-paper questions among the matching ones."""
    return await questions_service.admin_list_questions(
        session,
        unit_number=unit,
        question_type=type,
        difficulty=difficulty,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/bulk", status_code=status.HTTP_204_NO_CONTENT, summary="Approve, mark outdated or delete"
)
async def bulk(req: BulkQuestionsIn, admin: CurrentUserDep, session: SessionDep) -> Response:
    """All or nothing. `delete` removes unused questions; questions students already answered
    are archived instead (their answers stay). `approve` checks every question like publishing.

    Errors: 404 `QUESTION_NOT_FOUND` · 422 `QUESTION_INCOMPLETE` / `VALIDATION_ERROR`."""
    await questions_service.admin_bulk(session, req.ids, req.action)
    await admin_service.record_audit(
        session,
        admin,
        f"question.{req.action}",
        "question",
        "bulk",
        {"ids": [str(i) for i in req.ids]},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- quality review


@router.get("/quality", response_model=QualityQueueOut, summary="AI questions waiting for review")
async def quality_queue(admin: CurrentUserDep, session: SessionDep) -> QualityQueueOut:
    """Oldest first. Each item has the four checks (pass / review / fail + a note) and the
    open student reports per reason. `avg_review_minutes` covers the last 30 days."""
    return await quality_service.review_queue(session)


@router.post(
    "/{question_id}/review",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Approve or reject a question from the review queue",
)
async def review_question(
    question_id: uuid.UUID, req: ReviewDecisionIn, admin: CurrentUserDep, session: SessionDep
) -> Response:
    """`approve: true` publishes it (same rules as the editor), `false` rejects it.

    Errors: 404 `QUESTION_NOT_FOUND` · 422 `QUESTION_INCOMPLETE` / `VALIDATION_ERROR`."""
    await quality_service.record_decision(session, admin.id, question_id, req.approve)
    action = "question.review_approve" if req.approve else "question.review_reject"
    await admin_service.record_audit(session, admin, action, "question", question_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- past papers


@router.get("/past-papers", response_model=list[PastPaperOut], summary="Uploaded past papers")
async def list_past_papers(admin: CurrentUserDep, session: SessionDep) -> list[PastPaperOut]:
    """Newest year first. `extraction`: running (also while queued) | done | low_confidence
    (done, but some questions may be misread) | failed."""
    return await questions_service.admin_list_past_papers(session)


@router.post(
    "/past-papers",
    response_model=PastPaperOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a past paper PDF (questions are extracted in the background)",
)
async def upload_past_paper(
    admin: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="The paper (PDF, max 40 MB)")],
    year: Annotated[int, Form(ge=1990, le=2100)],
    paper_type: Annotated[PaperType, Form()],
    scheme: Annotated[UploadFile | None, File(description="Marking scheme (PDF)")] = None,
) -> PastPaperOut:
    """Multipart form. Returns the paper with `extraction: "running"`; poll
    `GET /admin/questions/past-papers` for `progress` (0-1).

    Errors: 409 `PAST_PAPER_EXISTS` · 413 `FILE_TOO_LARGE` · 415 `UNSUPPORTED_FILE_TYPE`
    (not a PDF) · 422 `EMPTY_FILE` / `VALIDATION_ERROR`."""
    paper = await questions_service.admin_upload_past_paper(
        session,
        admin.id,
        file=file,
        year=year,
        paper_type=paper_type,
        scheme=scheme,
        ai=ai,
        background_tasks=background_tasks,
    )
    await admin_service.record_audit(session, admin, "past_paper.upload", "past_paper", paper.id)
    return paper


@router.get(
    "/past-papers/{paper_id}/questions",
    response_model=list[PastPaperQuestionOut],
    summary="Questions extracted from a past paper",
)
async def past_paper_questions(
    paper_id: uuid.UUID, admin: CurrentUserDep, session: SessionDep
) -> list[PastPaperQuestionOut]:
    """In paper order. Errors: 404 `PAST_PAPER_NOT_FOUND`."""
    return await questions_service.admin_past_paper_questions(session, paper_id)


@router.put(
    "/past-papers/questions/{question_id}",
    response_model=PastPaperQuestionOut,
    summary="Save the model answer and keywords of an extracted question",
)
async def save_past_paper_answer(
    question_id: uuid.UUID, req: PastPaperAnswerIn, admin: CurrentUserDep, session: SessionDep
) -> PastPaperQuestionOut:
    """Keywords are trimmed and de-duplicated. Errors: 404 `PAST_PAPER_QUESTION_NOT_FOUND`."""
    question = await questions_service.admin_save_past_paper_answer(session, question_id, req)
    await admin_service.record_audit(
        session, admin, "past_paper.answer", "past_paper_question", question_id
    )
    return question


# ---------------------------------------------------------------- editor


@router.post(
    "",
    response_model=AdminQuestionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a question",
)
async def create_question(
    req: AdminQuestionIn, admin: CurrentUserDep, session: SessionDep
) -> AdminQuestionOut:
    """`status: "approved"` publishes it: an MCQ then needs exactly one correct option and a
    misconception on every wrong option (422 `QUESTION_INCOMPLETE`, the problems are in
    `details`). Misconceptions are saved in `misconceptions` + `mcq_options.misconception_id`.

    Errors: 404 `UNIT_NOT_FOUND` / `TOPIC_NOT_FOUND` / `CONCEPT_NOT_FOUND` ·
    422 `SYLLABUS_MISMATCH` (e.g. the topic is in another unit)."""
    question = await questions_service.admin_create_question(session, admin.id, req)
    await admin_service.record_audit(session, admin, "question.create", "question", question.id)
    return question


@router.get("/{question_id}", response_model=AdminQuestionOut, summary="One question (editor)")
async def get_question(
    question_id: uuid.UUID, admin: CurrentUserDep, session: SessionDep
) -> AdminQuestionOut:
    """Errors: 404 `QUESTION_NOT_FOUND`."""
    return await questions_service.admin_get_question(session, question_id)


@router.put("/{question_id}", response_model=AdminQuestionOut, summary="Save a question")
async def update_question(
    question_id: uuid.UUID, req: AdminQuestionIn, admin: CurrentUserDep, session: SessionDep
) -> AdminQuestionOut:
    """Same rules as create. Options are matched by label (A-E), so students' saved answers
    keep pointing at the right option. Errors: 404 `QUESTION_NOT_FOUND` and as create."""
    question = await questions_service.admin_update_question(session, admin.id, question_id, req)
    await admin_service.record_audit(session, admin, "question.update", "question", question_id)
    return question


# ---------------------------------------------------------------- MCQ -> misconception mapping
# A second router, because these paths are /admin/options/..., not /admin/questions/...
options_router = APIRouter(prefix="/options", tags=["Admin: questions"])


@options_router.put(
    "/{option_id}/misconception",
    response_model=OptionMisconceptionOut,
    summary="Link a wrong MCQ option to its misconception",
)
async def set_option_misconception(
    option_id: uuid.UUID, req: OptionMisconceptionIn, admin: CurrentUserDep, session: SessionDep
) -> OptionMisconceptionOut:
    """`{misconception: "..."}`; null or "" removes the link. The same text is stored once per
    concept and reused. Errors: 404 `OPTION_NOT_FOUND` · 422 `CORRECT_OPTION_NO_MISCONCEPTION`."""
    option = await questions_service.admin_set_option_misconception(
        session, admin.id, option_id, req.misconception
    )
    await admin_service.record_audit(
        session, admin, "option.misconception", "mcq_option", option_id
    )
    return option
