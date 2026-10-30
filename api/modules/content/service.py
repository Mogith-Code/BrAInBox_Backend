"""Business logic for the content module. Owner: Samni.

Uploads to summarise (async, the app polls):
    1. POST /uploads/text or /uploads/pdf -> an `uploads` row (queued) + a SUMMARIZE_UPLOAD job,
       answer 202 at once. A PDF is first saved to storage (api/core/storage.py).
    2. In the background: run the job in the ai_service (pipelines/summarization), then save a
       `summaries` row and set the upload to "succeeded" (or "failed")
    3. GET /uploads/{id} -> status, and the summary once it is ready (or why it failed)

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import logging
import uuid
from typing import Any

from fastapi import BackgroundTasks, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import jobs, storage
from api.core.ai_client import AIClient
from api.core.errors import AppError, ForbiddenError, NotFoundError
from api.core.security import CurrentUser
from api.modules.content import repository
from api.modules.content.schemas import (
    MAX_PDF_BYTES,
    PDF_MIME_TYPE,
    TEXT_MIME_TYPE,
    ModuleStatus,
    UploadError,
    UploadOut,
    UploadSummary,
    UploadTextRequest,
)
from api.modules.syllabus import service as syllabus_service
from shared.db.models import AIJob, Summary, Upload
from shared.db.session import SessionLocal
from shared.enums import JobStatus, JobType

logger = logging.getLogger(__name__)

MODULE_NAME = "content"

# Text notes are not stored as a file: the text travels in the job payload (ai_jobs.input).
TEXT_FILE_PATH = ""

# Shown to the student when processing failed for any other reason (AI down, timeout, bug).
# The real cause stays in the logs and in ai_jobs.error.
FAILED_ERROR = UploadError(
    code="SUMMARIZATION_FAILED", message="We could not summarise these notes. Please try again."
)

# Problems with the student's input, found by the summarization pipeline
# (ai_service/pipelines/summarization/preprocess.py). Their message is shown as it is.
INPUT_ERROR_CODES = {
    "EMPTY_NOTES",
    "NO_TEXT_IN_FILE",
    "NOTES_TOO_LONG",
    "NOT_ENGLISH",
    "UNREADABLE_FILE",
    "UNSUPPORTED_FILE_TYPE",
}


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# --------------------------------------------------------------------------- responses


def failure_error(job_error: str | None) -> UploadError:
    """What to tell the student about a failed job. `job_error` looks like "CODE: message"."""
    code, _, message = (job_error or "").partition(": ")
    if code in INPUT_ERROR_CODES and message:
        return UploadError(code=code, message=message)
    return FAILED_ERROR


def upload_out(
    upload: Upload, summary: Summary | None = None, error: UploadError | None = None
) -> UploadOut:
    """Build the API response of an upload. Pure function: no database, no AI."""
    failed = upload.processing_status == JobStatus.FAILED
    return UploadOut(
        upload_id=upload.id,
        input_type="pdf" if upload.mime_type == PDF_MIME_TYPE else "text",
        title=upload.file_name,  # uploads.file_name holds the title the student gave
        topic_id=upload.topic_id,
        status=upload.processing_status,
        summary=UploadSummary.model_validate(summary) if summary and not failed else None,
        error=(error or FAILED_ERROR) if failed else None,
        created_at=upload.created_at,
    )


# --------------------------------------------------------------------------- create


async def _unit_title(session: AsyncSession, topic_id: uuid.UUID | None) -> str:
    """Unit title of the topic, for the prompt. Raises 404 TOPIC_NOT_FOUND for an unknown id."""
    if topic_id is None:
        return ""
    [topic] = await syllabus_service.get_topics(session, [topic_id])
    return topic.unit_title


async def _queue_upload(
    session: AsyncSession,
    user: CurrentUser,
    upload: Upload,
    payload: dict[str, Any],
    ai: AIClient,
    background_tasks: BackgroundTasks,
) -> UploadOut:
    """Create the SUMMARIZE_UPLOAD job (this also commits the upload) and run it in the
    background. Returns the upload with status "queued"."""
    job = await jobs.create_job(session, JobType.SUMMARIZE_UPLOAD, payload, requested_by=user.id)
    await session.refresh(upload)  # load created_at (set by the database)

    # Runs after the response is sent (JOB_RUNNER=local, like core/jobs.enqueue_job), and also
    # saves the summary on the upload.
    # TODO(Samni): move to Cloud Tasks together with core/jobs once JOB_RUNNER=cloudtasks exists.
    background_tasks.add_task(process_upload, upload.id, job.id, ai)
    logger.info("Upload %s queued as job %s (%s bytes)", upload.id, job.id, upload.size_bytes)
    return upload_out(upload)


async def create_text_upload(
    session: AsyncSession,
    user: CurrentUser,
    req: UploadTextRequest,
    ai: AIClient,
    background_tasks: BackgroundTasks,
) -> UploadOut:
    """Accept text notes and queue the summary."""
    unit_title = await _unit_title(session, req.topic_id)
    upload = await repository.create_upload(
        session,
        user_id=user.id,
        topic_id=req.topic_id,
        file_name=req.title,
        file_path=TEXT_FILE_PATH,
        mime_type=TEXT_MIME_TYPE,
        size_bytes=len(req.text.encode("utf-8")),
    )
    # Payload of ai_service/pipelines/summarization/summarize.py (`upload_id` and `options` are
    # kept on the job row for reference; the pipeline does not need them yet).
    payload = {
        "upload_id": str(upload.id),
        "topic_title": req.title,
        "unit_title": unit_title,
        "topic_id": str(req.topic_id) if req.topic_id else None,
        "text": req.text,
        "options": req.options.model_dump(),
    }
    return await _queue_upload(session, user, upload, payload, ai, background_tasks)


async def read_pdf(file: UploadFile) -> bytes:
    """The bytes of an uploaded PDF, after checking type and size."""
    if file.content_type != PDF_MIME_TYPE:
        raise AppError(
            f"Only PDF files ({PDF_MIME_TYPE}) are accepted",
            code="UNSUPPORTED_FILE_TYPE",
            status_code=415,
        )
    data = await file.read(MAX_PDF_BYTES + 1)  # never read more than the limit
    if not data:
        raise AppError("The file is empty", code="EMPTY_FILE", status_code=422)
    if len(data) > MAX_PDF_BYTES:
        raise AppError(
            f"The file is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB",
            code="FILE_TOO_LARGE",
            status_code=413,
        )
    if not data.startswith(b"%PDF-"):
        raise AppError("The file is not a valid PDF", code="UNSUPPORTED_FILE_TYPE", status_code=415)
    return data


async def create_pdf_upload(
    session: AsyncSession,
    user: CurrentUser,
    file: UploadFile,
    title: str,
    topic_id: uuid.UUID | None,
    ai: AIClient,
    background_tasks: BackgroundTasks,
) -> UploadOut:
    """Save the PDF to storage and queue its summary (the ai_service extracts the text)."""
    data = await read_pdf(file)
    unit_title = await _unit_title(session, topic_id)

    # The file goes to storage first, so no row exists for a file that could not be saved.
    upload_id = uuid.uuid4()
    file_path = f"uploads/{user.id}/{upload_id}.pdf"
    await run_in_threadpool(storage.upload_bytes, file_path, data, PDF_MIME_TYPE)

    upload = await repository.create_upload(
        session,
        upload_id=upload_id,
        user_id=user.id,
        topic_id=topic_id,
        file_name=title.strip(),
        file_path=file_path,
        mime_type=PDF_MIME_TYPE,
        size_bytes=len(data),
    )
    payload = {
        "upload_id": str(upload.id),
        "topic_title": title.strip(),
        "unit_title": unit_title,
        "topic_id": str(topic_id) if topic_id else None,
        "file_path": file_path,
        "mime_type": PDF_MIME_TYPE,
    }
    return await _queue_upload(session, user, upload, payload, ai, background_tasks)


# --------------------------------------------------------------------------- process


async def process_upload(upload_id: uuid.UUID, job_id: uuid.UUID, ai: AIClient) -> None:
    """Background task: summarise one upload. Uses its own DB session."""
    async with SessionLocal() as session:
        upload = await repository.get_upload(session, upload_id)
        job = await repository.get_job(session, job_id)
        if upload is None or job is None:
            logger.error("Upload %s or job %s not found", upload_id, job_id)
            return
        await run_upload_job(session, upload, job, ai)


async def run_upload_job(session: AsyncSession, upload: Upload, job: AIJob, ai: AIClient) -> None:
    """Run the job, then save the summary and the final status on the upload."""
    upload.processing_status = JobStatus.RUNNING
    # run_job_inline commits "running", calls the ai_service and stores the outcome on the job.
    # It never raises: AI errors, input errors and timeouts end as job status "failed".
    job = await jobs.run_job_inline(session, job, ai)

    output = (job.result or {}).get("result", {}) if job.status == JobStatus.SUCCEEDED else {}
    body_md = output.get("body_md")
    if not body_md:
        if job.status == JobStatus.SUCCEEDED:
            logger.error("Job %s succeeded without a summary", job.id)
        upload.processing_status = JobStatus.FAILED
        await session.commit()
        return

    try:
        await repository.save_summary(
            session,
            user_id=upload.user_id,
            upload_id=upload.id,
            topic_id=upload.topic_id,
            body_md=body_md,
            prompt_version=output.get("prompt_version"),
        )
        upload.processing_status = JobStatus.SUCCEEDED
        await session.commit()
    except Exception:
        logger.exception("Could not save the summary of upload %s", upload.id)
        await session.rollback()
        upload.processing_status = JobStatus.FAILED
        await session.commit()


# --------------------------------------------------------------------------- read


async def get_upload(session: AsyncSession, user: CurrentUser, upload_id: uuid.UUID) -> UploadOut:
    """Status of an upload, with its summary once it has succeeded (or why it failed)."""
    upload = await repository.get_upload(session, upload_id)
    if upload is None:
        raise NotFoundError(f"Upload '{upload_id}' not found", code="UPLOAD_NOT_FOUND")
    if upload.user_id != user.id and not user.is_admin:
        raise ForbiddenError("This upload belongs to another student")

    if upload.processing_status == JobStatus.SUCCEEDED:
        summary = await repository.get_summary_for_upload(session, upload.id)
        return upload_out(upload, summary)
    if upload.processing_status == JobStatus.FAILED:
        job = await repository.get_upload_job(session, upload)
        return upload_out(upload, error=failure_error(job.error if job else None))
    return upload_out(upload)


# TODO(Samni): list_topic_notes(topic_id) (approved only)
# TODO(Samni): library CRUD
