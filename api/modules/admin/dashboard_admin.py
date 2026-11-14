"""Admin routes: dashboard. Owner: Samni.

Mounted under /api/v1/admin/dashboard by `admin/router.py`, which already
requires the admin role for every route in this file.

    GET /admin/dashboard     KPIs, 14-day activity, newest reports, most missed topics

Built by `admin/service.build_dashboard` from the other modules' services (no SQL here).
"""

from fastapi import APIRouter, Request

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.admin import service as admin_service
from api.modules.admin.schemas import DashboardOut

router = APIRouter(prefix="/dashboard", tags=["Admin: dashboard"])


@router.get("", response_model=DashboardOut, summary="Admin dashboard")
async def dashboard(request: Request, admin: CurrentUserDep, session: SessionDep) -> DashboardOut:
    """KPIs (`kind`: students | quizzes | aiReview | reports), each with a delta, a trend and
    the last 8 days. **students** = with study activity in the last 7 days (vs the 7 before);
    **quizzes** = quizzes / papers / diagnostics finished today (vs yesterday); **aiReview** =
    AI questions + notes + diagrams waiting for review (`warning` when some wait over 48 h);
    **reports** = open moderation items. `activity` covers 14 days; `missed_topics` the
    5 most missed topics of the last 30 days. Admins' own activity is never counted."""
    return await admin_service.build_dashboard(session, str(request.base_url))
