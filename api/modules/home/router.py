"""HTTP endpoints for the home module. Owner: Samni.

    GET    /api/v1/home/summary          everything the home dashboard shows
    PATCH  /api/v1/home/plan/{item_id}   {done: true|false} -> the updated plan item

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.home import service
from api.modules.home.schemas import HomeSummary, PlanItemUpdate
from api.modules.recommendations.schemas import PlanItemOut

router = APIRouter(prefix="/home", tags=["Home"])


@router.get("/summary", response_model=HomeSummary, summary="Home dashboard summary")
async def get_summary(user: CurrentUserDep, session: SessionDep, ai: AIClientDep) -> HomeSummary:
    """Greeting, streak, days to A/L, next best action, today's plan, mastery, continue learning."""
    return await service.get_summary(session, user, ai)


@router.patch("/plan/{item_id}", response_model=PlanItemOut, summary="Tick / untick a plan item")
async def update_plan_item(
    item_id: uuid.UUID, req: PlanItemUpdate, user: CurrentUserDep, session: SessionDep
) -> PlanItemOut:
    return await service.set_plan_item(session, user, item_id, req.done)
