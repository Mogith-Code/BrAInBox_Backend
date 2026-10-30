"""HTTP endpoints for the content module. Owner: Samni.

Implemented (summarization module):
    POST   /api/v1/uploads/text                            Text notes -> queued SUMMARIZE_UPLOAD job
    POST   /api/v1/uploads/pdf                             PDF upload -> storage + queued SUMMARIZE_UPLOAD job
    GET    /api/v1/uploads/{id}                            Upload status + summary

Planned endpoints (details in README.md):
    GET    /api/v1/topics/{id}/notes                       Approved notes for a topic (full + short)
    GET    /api/v1/library                                 My saved items
    POST   /api/v1/library                                 Save an item
    DELETE /api/v1/library/{id}                            Remove an item

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile, status

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.content import service
from api.modules.content.schemas import (
    MAX_TITLE_CHARS,
    ModuleStatus,
    UploadOut,
    UploadTextRequest,
)

router = APIRouter(tags=["Content"])


@router.get("/content/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Samni): replace this placeholder with the real endpoints listed above.
    return await service.get_status()


@router.post(
    "/uploads/text",
    response_model=UploadOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Summarise text notes (returns at once, then poll GET /uploads/{upload_id})",
)
async def upload_text(
    req: UploadTextRequest,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
) -> UploadOut:
    """202 means the notes were **accepted**, not summarised: `status` is `queued`.
    Poll `GET /api/v1/uploads/{upload_id}` until `status` is `succeeded` or `failed`.

    Errors: 401 not logged in · 404 `TOPIC_NOT_FOUND` · 422 `VALIDATION_ERROR`
    (empty text, text over 60,000 characters, unknown option value)."""
    return await service.create_text_upload(session, user, req, ai, background_tasks)


@router.post(
    "/uploads/pdf",
    response_model=UploadOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Summarise a PDF (returns at once, then poll GET /uploads/{upload_id})",
)
async def upload_pdf(
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="PDF file (application/pdf), at most 10 MB")],
    title: Annotated[str, Form(min_length=1, max_length=MAX_TITLE_CHARS, pattern=r"\S")],
    topic_id: Annotated[uuid.UUID | None, Form()] = None,
) -> UploadOut:
    """multipart/form-data with the fields `file`, `title` and optionally `topic_id`.
    202 means the file was **accepted** and saved: poll `GET /api/v1/uploads/{upload_id}`.

    Errors: 401 not logged in · 404 `TOPIC_NOT_FOUND` · 413 `FILE_TOO_LARGE` ·
    415 `UNSUPPORTED_FILE_TYPE` · 422 `EMPTY_FILE` / `VALIDATION_ERROR` ·
    503 `STORAGE_NOT_CONFIGURED`. A PDF without readable text (e.g. scanned) is accepted, then
    fails with `error.code` = `NO_TEXT_IN_FILE`."""
    return await service.create_pdf_upload(
        session, user, file, title, topic_id, ai, background_tasks
    )


@router.get(
    "/uploads/{upload_id}",
    response_model=UploadOut,
    summary="Upload status and summary",
)
async def get_upload(upload_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> UploadOut:
    """`status`: `queued` → `running` → `succeeded` (with `summary`) or `failed` (with `error`).

    `error.code` of a failed upload: `EMPTY_NOTES`, `NO_TEXT_IN_FILE`, `NOTES_TOO_LONG`,
    `NOT_ENGLISH`, `UNREADABLE_FILE` (the student can fix these) or `SUMMARIZATION_FAILED`
    (try again later).

    Errors: 401 not logged in · 403 another student's upload · 404 `UPLOAD_NOT_FOUND`."""
    return await service.get_upload(session, user, upload_id)
