"""Create AI jobs and hand them to a runner.

Flow:
    1. A service calls `create_job(...)` -> a row in `ai_jobs` with status "queued".
    2. It calls `enqueue_job(job, background_tasks)` and answers 202 with the job id.
    3. The runner calls the ai_service, then stores the result / error on the row. A module can
       register a handler for its job type (`register_job_handler`) to save its own rows in the
       SAME commit as status "succeeded".
    4. The app polls GET /api/v1/jobs/{id}.

JOB_RUNNER=local       -> FastAPI BackgroundTasks (same process; dev, tests and small servers)
JOB_RUNNER=cloudtasks  -> Google Cloud Tasks: a task is created that calls
                          POST {JOBS_TARGET_URL}/api/v1/internal/jobs/{id}/run on this API
                          (api/modules/jobs/router.py), so the work survives the instance that
                          accepted the request and is retried by the queue if the call fails.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import BackgroundTasks
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.ai_client import SERVICE_TOKEN_HEADER, AIClient, get_ai_client
from api.core.config import get_settings
from api.core.errors import AppError
from shared.db.models import AIJob
from shared.db.session import SessionLocal
from shared.enums import JobStatus, JobType

logger = logging.getLogger(__name__)

CLOUD_TASKS_API = "https://cloudtasks.googleapis.com/v2"
CLOUD_TASKS_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# Called after a job succeeded, before the final commit (see run_job_inline).
OnSuccess = Callable[[AIJob], Awaitable[None]]
# A module's handler for its job type: (session, job) -> None. No commit inside.
JobHandler = Callable[[AsyncSession, AIJob], Awaitable[None]]

_success_handlers: dict[JobType, JobHandler] = {}
_failure_handlers: dict[JobType, JobHandler] = {}


def register_job_handler(
    job_type: JobType, on_success: JobHandler, on_failure: JobHandler | None = None
) -> None:
    """Let a module save its rows when a job of `job_type` finishes (called at import time).

    `on_success(session, job)` runs in the commit that marks the job "succeeded"; if it raises,
    the job ends as "failed". `on_failure(session, job)` runs after a failed job, e.g. to mark
    the module's own row as failed too.
    """
    _success_handlers[job_type] = on_success
    if on_failure is not None:
        _failure_handlers[job_type] = on_failure


async def create_job(
    session: AsyncSession,
    job_type: JobType,
    payload: dict[str, Any],
    requested_by: uuid.UUID | None = None,
) -> AIJob:
    job = AIJob(
        job_type=job_type, status=JobStatus.QUEUED, input=payload, requested_by=requested_by
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


def enqueue_job(job: AIJob, background_tasks: BackgroundTasks, ai: AIClient | None = None) -> None:
    """Start the job after the response is sent. `ai` is the request's AI client (tests pass a
    fake one); without it the runner creates its own."""
    runner = get_settings().JOB_RUNNER
    if runner == "local":
        background_tasks.add_task(run_job_now, job.id, ai)
    elif runner == "cloudtasks":
        background_tasks.add_task(create_cloud_task, job.id)
    else:
        raise ValueError(f"Unknown JOB_RUNNER: {runner}")


async def run_job_inline(
    session: AsyncSession, job: AIJob, client: AIClient, on_success: OnSuccess | None = None
) -> AIJob:
    """Run a job right now, inside the current request, and save the outcome on the row.

    Use this when the client waits for the answer (e.g. generating a paper).
    `job.result` is the ai_service response: {"job_id", "job_type", "result": {...}}.

    `on_success(job)` lets the owning module save its rows (e.g. the finished visual) in the
    SAME commit as status "succeeded", so the app never sees "succeeded" before the data
    exists. If it raises, the job ends as "failed".
    """
    job.status = JobStatus.RUNNING
    job.started_at = datetime.now(UTC)
    job.attempts += 1
    await session.commit()

    try:
        job.result = await client.run_job(str(job.id), job.job_type.value, job.input)
        if on_success is not None:
            await on_success(job)
        job.status = JobStatus.SUCCEEDED
    except Exception as exc:
        logger.exception("Job %s failed", job.id)
        # The handler may have left the session in a failed transaction.
        await session.rollback()
        # AppErrors keep their code, e.g. "EMPTY_NOTES: The notes are empty...", so the module
        # that owns the job can tell the student what went wrong.
        job.error = f"{exc.code}: {exc.message}" if isinstance(exc, AppError) else str(exc)
        job.status = JobStatus.FAILED
    job.finished_at = datetime.now(UTC)
    await session.commit()
    return job


async def run_job_now(job_id: uuid.UUID, ai: AIClient | None = None) -> JobStatus | None:
    """Run one queued job with its module's handlers. Uses its own DB session.

    Only a QUEUED job is run, so a Cloud Tasks retry of a job that already ran does nothing.
    Returns the job's final status (None if the job does not exist).
    """
    async with SessionLocal() as session:
        job = await session.get(AIJob, job_id)
        if job is None:
            logger.error("Job %s not found", job_id)
            return None
        if job.status != JobStatus.QUEUED:
            return job.status
        handler = _success_handlers.get(job.job_type)

        async def on_success(done: AIJob) -> None:
            if handler is not None:
                await handler(session, done)

        job = await run_job_inline(session, job, ai or get_ai_client(), on_success=on_success)
        failure = _failure_handlers.get(job.job_type)
        if job.status == JobStatus.FAILED and failure is not None:
            try:
                await failure(session, job)
                await session.commit()
            except Exception:
                logger.exception("Failure handler of job %s crashed", job.id)
                await session.rollback()
        return job.status


# --------------------------------------------------------------------------- Cloud Tasks


def _access_token() -> str:
    """A Google access token for this service's account (blocking: use run_in_threadpool)."""
    import google.auth
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(scopes=[CLOUD_TASKS_SCOPE])
    credentials.refresh(Request())
    return str(credentials.token)


def cloud_task_body(job_id: uuid.UUID) -> dict[str, Any]:
    """Pure: the Cloud Tasks request that makes the queue call our internal run endpoint."""
    settings = get_settings()
    http_request: dict[str, Any] = {
        "httpMethod": "POST",
        "url": f"{settings.JOBS_TARGET_URL.rstrip('/')}/api/v1/internal/jobs/{job_id}/run",
        "headers": {SERVICE_TOKEN_HEADER: settings.AI_SERVICE_TOKEN},
    }
    if settings.CLOUD_TASKS_SERVICE_ACCOUNT:
        # Signed by Google, so the call is also traceable to our service account.
        http_request["oidcToken"] = {"serviceAccountEmail": settings.CLOUD_TASKS_SERVICE_ACCOUNT}
    return {
        "task": {
            "httpRequest": http_request,
            # The longest a job may take before the queue retries it.
            "dispatchDeadline": f"{settings.CLOUD_TASKS_DEADLINE_SECONDS}s",
        }
    }


async def create_cloud_task(job_id: uuid.UUID) -> None:
    """Put the job on the Cloud Tasks queue. If that fails the job is marked failed, so the
    app stops polling and shows an error instead of waiting forever."""
    settings = get_settings()
    project = settings.CLOUD_TASKS_PROJECT or settings.FIREBASE_PROJECT_ID
    queue = (
        f"{CLOUD_TASKS_API}/projects/{project}/locations/{settings.CLOUD_TASKS_LOCATION}"
        f"/queues/{settings.CLOUD_TASKS_QUEUE}/tasks"
    )
    try:
        if not project or not settings.JOBS_TARGET_URL:
            raise RuntimeError("CLOUD_TASKS_PROJECT and JOBS_TARGET_URL must be set")
        token = await run_in_threadpool(_access_token)
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                queue, json=cloud_task_body(job_id), headers={"Authorization": f"Bearer {token}"}
            )
            response.raise_for_status()
    except Exception as exc:
        logger.exception("Could not create a Cloud Task for job %s", job_id)
        async with SessionLocal() as session:
            job = await session.get(AIJob, job_id)
            if job is not None and job.status == JobStatus.QUEUED:
                job.status = JobStatus.FAILED
                job.error = f"Could not queue the job: {exc}"
                job.finished_at = datetime.now(UTC)
                failure = _failure_handlers.get(job.job_type)
                if failure is not None:
                    await failure(session, job)
                await session.commit()
