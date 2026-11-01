"""Business logic for the jobs module. Owner: shared.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.errors import NotFoundError
from api.core.security import CurrentUser
from api.modules.jobs import repository
from api.modules.jobs.schemas import JobOut
from shared.db.models import AIJob
from shared.enums import JobStatus

GENERIC_ERROR = "Something went wrong while making this. Please try again."
BUSY_ERROR = "The AI is busy right now. Please try again in a few minutes."
# core/jobs.py saves AppErrors as "CODE: message"; anything else is a technical message.
_CODED_ERROR_RE = re.compile(r"^(?P<code>[A-Z][A-Z0-9_]+): (?P<message>.+)$", re.S)


def readable_error(error: str | None) -> tuple[str, str | None]:
    """(message for the student, error code) from `ai_jobs.error`.

    Input errors from a pipeline (e.g. "NOT_BIOLOGY: I can only draw Biology visuals.") keep
    their message. Technical errors (stack traces, timeouts) become a generic sentence.
    """
    match = _CODED_ERROR_RE.match(error or "")
    if match is None:
        return GENERIC_ERROR, None
    code = match.group("code")
    if code == "AI_SERVICE_UNAVAILABLE":
        return BUSY_ERROR, code
    return match.group("message").strip(), code


def job_out(job: AIJob) -> JobOut:
    """Build the API response. Pure function: no database."""
    done = job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)
    result = None
    if job.status == JobStatus.SUCCEEDED:
        # The row holds the ai_service response {"job_id", "job_type", "result": {...}}.
        result = (job.result or {}).get("result")
    error = code = None
    if job.status == JobStatus.FAILED:
        error, code = readable_error(job.error)
    return JobOut(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress=1.0 if done else 0.0,
        result=result,
        error=error,
        error_code=code,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


async def get_job(session: AsyncSession, user: CurrentUser, job_id: uuid.UUID) -> JobOut:
    """A job of this user (admins can see every job). Someone else's job is a 404 too."""
    job = await repository.get_job(session, job_id)
    if job is None or (job.requested_by != user.id and not user.is_admin):
        raise NotFoundError(f"Job '{job_id}' not found", code="JOB_NOT_FOUND")
    return job_out(job)
