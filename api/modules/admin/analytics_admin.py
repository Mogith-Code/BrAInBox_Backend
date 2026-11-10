"""Admin routes: analytics. Owner: Keshomigha.

Mounted under /api/v1/admin/analytics by `admin/router.py`, which already
requires the admin role for every route in this file.

    GET /admin/analytics/overview      students, active students, attempts, MCQ answers
    GET /admin/analytics/performance   average mastery per unit, most-missed topics, misconceptions
    GET /admin/analytics/ai-usage      AI requests per feature and day (ai_usage_log)

`?days=` picks the period (default 30), ending today. Totals over all students; admins' own
activity is left out.

Admin routes call the services of the owning modules (here `api.modules.performance.service`);
they do not have their own SQL.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.admin.schemas import ModuleStatus
from api.modules.performance import service as performance_service
from api.modules.performance.schemas import (
    AnalyticsAIUsage,
    AnalyticsOverview,
    AnalyticsPerformance,
)

router = APIRouter(prefix="/analytics", tags=["Admin: analytics"])

DaysQuery = Annotated[int, Query(ge=1, le=365, description="Period in days, ending today")]


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    return ModuleStatus(module="analytics_admin", status="todo")


@router.get("/overview", response_model=AnalyticsOverview, summary="Students and activity")
async def overview(
    admin: CurrentUserDep, session: SessionDep, days: DaysQuery = 30
) -> AnalyticsOverview:
    """`active_change_percent` compares with the period before; null when that had no activity."""
    return await performance_service.analytics_overview(session, days)


@router.get(
    "/performance",
    response_model=AnalyticsPerformance,
    summary="Average mastery per unit, most-missed topics and common misconceptions",
)
async def performance(
    admin: CurrentUserDep, session: SessionDep, days: DaysQuery = 30
) -> AnalyticsPerformance:
    """`days` applies to topics and misconceptions. `units` is the current level. A topic needs
    `min_answers_per_topic` answers to be listed."""
    return await performance_service.analytics_performance(session, days)


@router.get("/ai-usage", response_model=AnalyticsAIUsage, summary="AI requests per feature and day")
async def ai_usage(
    admin: CurrentUserDep, session: SessionDep, days: DaysQuery = 30
) -> AnalyticsAIUsage:
    """`total_cost_usd`, `input_tokens` and `output_tokens` are null when they weren't recorded
    (not 0). The AI service only logs the calls themselves for now."""
    return await performance_service.analytics_ai_usage(session, days)
