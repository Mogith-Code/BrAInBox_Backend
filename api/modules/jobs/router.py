"""HTTP endpoints for the jobs module. Owner: shared.

Implemented:
    GET    /api/v1/jobs/{job_id}                           Job status + result (only the requester or an admin)
    POST   /api/v1/internal/jobs/{job_id}/run              Run a queued job (Cloud Tasks only, service token)

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Header

from api.core import jobs
from api.core.ai_client import SERVICE_TOKEN_HEADER
from api.core.config import get_settings
from api.core.database import SessionDep
from api.core.errors import UnauthorizedError
from api.core.security import CurrentUserDep
from api.modules.jobs import service
from api.modules.jobs.schemas import JobOut

router = APIRouter(tags=["Jobs"])


@router.get("/jobs/{job_id}", response_model=JobOut, summary="Status of an AI job (poll this)")
async def get_job(job_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> JobOut:
    """Poll every 1-2 seconds until `status` is `succeeded` (read `result`) or `failed`
    (show `error`, a sentence for the student).

    Errors: 401 not logged in · 404 `JOB_NOT_FOUND` (unknown, or another student's job)."""
    return await service.get_job(session, user, job_id)


@router.post("/internal/jobs/{job_id}/run", include_in_schema=False)
async def run_job(
    job_id: uuid.UUID,
    service_token: Annotated[str, Header(alias=SERVICE_TOKEN_HEADER)] = "",
) -> dict[str, str | None]:
    """Called by Cloud Tasks (JOB_RUNNER=cloudtasks), never by the app: it needs the service
    token instead of a login. Always answers 200 once the job ran, even when the job itself
    failed (the failure is stored on the job), so the queue only retries real delivery errors."""
    expected = get_settings().AI_SERVICE_TOKEN
    if not expected or not hmac.compare_digest(service_token.encode(), expected.encode()):
        raise UnauthorizedError("Missing or invalid service token", code="INVALID_SERVICE_TOKEN")
    status = await jobs.run_job_now(job_id)
    return {"job_id": str(job_id), "status": status.value if status else None}
