"""HTTP endpoints for the performance module. Owner: Keshomigha.

Implemented:
    GET    /api/v1/insights/topics                         Topic-wise MCQ scores, weak topics,
                                                           feedback (own data; ?attempt_id= for one)

Planned endpoints (details in README.md):
    GET    /api/v1/insights/summary                        Overall progress
    GET    /api/v1/insights/units                          Mastery per unit
    GET    /api/v1/insights/concepts                       Weakest concepts
    GET    /api/v1/mistakes                                My mistakes (filter by type/unit)
    (service) record_mistake() and update_mastery() called by quizzes/exams/evaluation

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.performance import service
from api.modules.performance.schemas import ModuleStatus, TopicInsightsResponse

router = APIRouter(tags=["Performance"])


@router.get(
    "/performance/status", response_model=ModuleStatus, summary="Placeholder: module status"
)
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    return await service.get_status()


@router.get(
    "/insights/topics",
    response_model=TopicInsightsResponse,
    summary="My topic-wise MCQ scores, weak topics and feedback",
)
async def topic_insights(
    user: CurrentUserDep, session: SessionDep, attempt_id: uuid.UUID | None = None
) -> TopicInsightsResponse:
    """Scores every Biology topic from the student's own finished attempts (or only
    `attempt_id`). Topics with fewer than 5 valid answers are marked `insufficient_data`."""
    return await service.get_topic_insights(session, user, attempt_id)
