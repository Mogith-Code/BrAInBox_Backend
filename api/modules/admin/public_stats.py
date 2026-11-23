"""The one admin route that needs no login: totals for the sign-in page. Owner: Samni.

    GET /public/console-stats     AI items to review, students, evaluation accuracy

It returns three numbers and never any personal data. Every other admin route stays behind
the admin role in `admin/router.py`.
"""

from fastapi import APIRouter

from api.core.database import SessionDep
from api.modules.admin import service as admin_service
from api.modules.admin.schemas import ConsoleStatsOut

router = APIRouter(prefix="/public", tags=["Public"])


@router.get("/console-stats", response_model=ConsoleStatsOut, summary="Sign-in page totals")
async def console_stats(session: SessionDep) -> ConsoleStatsOut:
    """Refreshed at most once a minute. `students` counts accounts that are not suspended."""
    return await admin_service.console_stats(session)
