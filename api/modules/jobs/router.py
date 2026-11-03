"""HTTP endpoints for the jobs module. Owner: shared.

Implemented:
    GET    /api/v1/jobs/{job_id}                           Job status + result (only the requester or an admin)

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter

from api.core.database import SessionDep
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
