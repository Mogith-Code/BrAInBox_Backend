"""HTTP endpoints for the recommendations module.

    GET    /api/v1/recommendations                 My next steps, most important first
    PATCH  /api/v1/recommendations/{id}            Mark in progress / done / dismissed
    GET    /api/v1/recommendations/{id}/outcome    Before / after for its concept (reassessment)
    GET    /api/v1/study-plan                      My weekly study plan (made on first request)
    POST   /api/v1/study-plan/regenerate           A new plan from the current recommendations
    PATCH  /api/v1/study-plan/items/{id}           Tick / untick an item
    PUT    /api/v1/study-plan/order                Reorder one day's items

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.recommendations import service
from api.modules.recommendations.schemas import (
    PlanItemUpdate,
    PlanOrderIn,
    ReassessmentOutcome,
    RecommendationList,
    RecommendationOut,
    RecommendationUpdate,
    StudyPlanItemOut,
    StudyPlanOut,
)

router = APIRouter(tags=["Recommendations"])


@router.get(
    "/recommendations",
    response_model=RecommendationList,
    summary="My next steps, each with the reason it was given",
)
async def list_recommendations(
    user: CurrentUserDep, session: SessionDep, ai: AIClientDep
) -> RecommendationList:
    """Rule-based and explainable: every item's `reason` says which of my answers caused it.
    Rebuilt from my current mastery and mistakes on each request."""
    return await service.list_recommendations(session, user, ai)


@router.patch(
    "/recommendations/{recommendation_id}",
    response_model=RecommendationOut,
    summary="Mark a recommendation in progress, done or dismissed",
)
async def update_recommendation(
    recommendation_id: uuid.UUID,
    req: RecommendationUpdate,
    user: CurrentUserDep,
    session: SessionDep,
) -> RecommendationOut:
    return await service.update_recommendation(session, user, recommendation_id, req.status)


@router.get(
    "/recommendations/{recommendation_id}/outcome",
    response_model=ReassessmentOutcome,
    summary="Before / after comparison for a recommendation's concept",
)
async def outcome(
    recommendation_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> ReassessmentOutcome:
    return await service.outcome(session, user, recommendation_id)


@router.get("/study-plan", response_model=StudyPlanOut, summary="My weekly study plan")
async def get_plan(user: CurrentUserDep, session: SessionDep, ai: AIClientDep) -> StudyPlanOut:
    """The top-priority actions fitted into my study days and hours. Created on the first
    request and again when the week is over."""
    return await service.get_plan(session, user, ai)


@router.post("/study-plan/regenerate", response_model=StudyPlanOut, summary="Make a new study plan")
async def regenerate_plan(
    user: CurrentUserDep, session: SessionDep, ai: AIClientDep
) -> StudyPlanOut:
    return await service.regenerate_plan(session, user, ai)


@router.patch(
    "/study-plan/items/{item_id}", response_model=StudyPlanItemOut, summary="Tick a plan item"
)
async def update_plan_item(
    item_id: uuid.UUID, req: PlanItemUpdate, user: CurrentUserDep, session: SessionDep
) -> StudyPlanItemOut:
    return await service.update_plan_item(session, user, item_id, req)


@router.put("/study-plan/order", response_model=StudyPlanOut, summary="Reorder one day's items")
async def reorder_plan(req: PlanOrderIn, user: CurrentUserDep, session: SessionDep) -> StudyPlanOut:
    return await service.reorder_plan(session, user, req.item_ids)
