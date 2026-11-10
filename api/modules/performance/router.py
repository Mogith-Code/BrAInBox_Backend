"""HTTP endpoints for the performance module. Owner: Keshomigha.

Implemented:
    GET    /api/v1/insights/topics                         Topic-wise MCQ scores, weak topics,
                                                           feedback (own data; ?attempt_id= for one)
    GET    /api/v1/insights/units                          Mastery per unit (own data)
    GET    /api/v1/insights/summary                        Overview: mastery, MCQs, topics, streak
    GET    /api/v1/mistakes                                My mistakes (filter by type/unit/status)
    PATCH  /api/v1/mistakes/{id}                           Mark a mistake fixed or open again
    (service) record_mistakes() called by quizzes/exams after marking

Planned endpoints (details in README.md):
    GET    /api/v1/insights/concepts                       Weakest concepts
    (service) update_mastery() called by quizzes/exams/evaluation

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from api.core.database import SessionDep
from api.core.pagination import Page, PageParamsDep
from api.core.security import CurrentUserDep
from api.modules.performance import service
from api.modules.performance.schemas import (
    InsightsSummaryResponse,
    MistakeOut,
    MistakeUpdate,
    ModuleStatus,
    TopicInsightsResponse,
    UnitInsightsResponse,
)
from shared.enums import MistakeType

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


@router.get(
    "/insights/units",
    response_model=UnitInsightsResponse,
    summary="My mastery per unit, with the change over the last week",
)
async def unit_insights(user: CurrentUserDep, session: SessionDep) -> UnitInsightsResponse:
    """Every current unit, Unit 1 first, with the newest mastery (0-100) and its grade.
    A unit never measured has `mastery: null` and status `not_attempted` (never 0 %)."""
    return await service.get_unit_insights(session, user)


@router.get(
    "/insights/summary",
    response_model=InsightsSummaryResponse,
    summary="My progress overview: mastery, MCQ score, topic levels and study streak",
)
async def insights_summary(user: CurrentUserDep, session: SessionDep) -> InsightsSummaryResponse:
    """The same numbers as `/insights/units` and `/insights/topics`, one per card, plus the
    streak and study days. A new student gets nulls and zeros, never made-up values."""
    return await service.get_insights_summary(session, user)


@router.get(
    "/mistakes",
    response_model=Page[MistakeOut],
    summary="My mistake journal: wrong MCQ answers, newest first",
)
async def list_mistakes(
    user: CurrentUserDep,
    session: SessionDep,
    paging: PageParamsDep,
    mistake_type: Annotated[MistakeType | None, Query(alias="type")] = None,
    unit_id: uuid.UUID | None = None,
    status: Literal["open", "resolved"] | None = None,
) -> Page[MistakeOut]:
    """Filters: `type`, `unit_id`, `status` (`open` or `resolved`). Paged with `page` and `size`."""
    resolved = None if status is None else status == "resolved"
    return await service.list_mistakes(
        session, user, paging, mistake_type=mistake_type, unit_id=unit_id, resolved=resolved
    )


@router.patch("/mistakes/{mistake_id}", response_model=MistakeOut, summary="Mark a mistake fixed")
async def update_mistake(
    mistake_id: uuid.UUID, req: MistakeUpdate, user: CurrentUserDep, session: SessionDep
) -> MistakeOut:
    """`{"resolved": true}` = fixed, `false` = open again. 404 `MISTAKE_NOT_FOUND` if it isn't
    yours."""
    return await service.update_mistake(session, user, mistake_id, req)
