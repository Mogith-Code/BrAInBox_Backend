"""Create AI jobs and hand them to a runner.

Flow:
    1. A service calls `create_job(...)` -> a row in `ai_jobs` with status "queued".
    2. It calls `enqueue_job(job, background_tasks)`.
    3. The runner calls the ai_service, then stores the result / error on the row.
    4. The app polls GET /api/v1/jobs/{id}.

JOB_RUNNER=local       -> FastAPI BackgroundTasks (same process, fine for dev)
JOB_RUNNER=cloudtasks  -> Google Cloud Tasks (TODO for production)
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.ai_client import get_ai_client
from api.core.config import get_settings
from shared.db.models import AIJob
from shared.db.session import SessionLocal
from shared.enums import JobStatus, JobType

logger = logging.getLogger(__name__)


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


def enqueue_job(job: AIJob, background_tasks: BackgroundTasks) -> None:
    runner = get_settings().JOB_RUNNER
    if runner == "local":
        background_tasks.add_task(run_job_now, job.id)
    elif runner == "cloudtasks":
        # TODO(Mogith): create a Cloud Task that POSTs to an internal endpoint which calls
        #   run_job_now(job_id). Needs a queue name + service account in config.
        raise NotImplementedError("JOB_RUNNER=cloudtasks is not implemented yet")
    else:
        raise ValueError(f"Unknown JOB_RUNNER: {runner}")


async def run_job_now(job_id: uuid.UUID) -> None:
    """Run one job: call the ai_service and save the outcome. Uses its own DB session."""
    async with SessionLocal() as session:
        job = await session.get(AIJob, job_id)
        if job is None:
            logger.error("Job %s not found", job_id)
            return
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.attempts += 1
        await session.commit()

        try:
            result = await get_ai_client().run_job(str(job.id), job.job_type.value, job.input)
            job.result = result
            job.status = JobStatus.SUCCEEDED
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            job.error = str(exc)
            job.status = JobStatus.FAILED
        job.finished_at = datetime.now(UTC)
        await session.commit()
