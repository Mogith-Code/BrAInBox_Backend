"""HTTP endpoints for the syllabus module. Owner: Keshomigha.

    GET    /api/v1/units                                   Current units with their topic counts
    GET    /api/v1/subjects/{subject_id}/units             Units of a subject + my progress
    GET    /api/v1/units/{unit_id}/topics                  Topics of a unit + sub-topics + my progress
    GET    /api/v1/topics/{topic_id}                       One topic with its sub-topics

Ids in the Learn paths can be the public code ("biology", "u6", "bio-6.1") or the UUID.

All need a logged-in user. Lists show the current syllabus only (outdated rows hidden).
Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.syllabus import service
from api.modules.syllabus.schemas import (
    LearnUnitOut,
    TopicDetailOut,
    UnitOut,
    UnitTopicsOut,
)

router = APIRouter(tags=["Syllabus"])


@router.get("/units", response_model=list[UnitOut], summary="All units of the current syllabus")
async def list_units(user: CurrentUserDep, session: SessionDep) -> list[UnitOut]:
    """Unit 1 first. `topic_count` counts current topics only."""
    return await service.get_units(session)


@router.get(
    "/subjects/{subject_id}/units",
    response_model=list[LearnUnitOut],
    summary="Units of a subject with my progress",
)
async def list_subject_units(
    subject_id: str, user: CurrentUserDep, session: SessionDep
) -> list[LearnUnitOut]:
    """`subject_id`: e.g. `biology`. Units in syllabus order.

    `progressPct` is the average of my topic scores in the unit (topics I have not started
    count as 0). `status`: `not_started` (no activity in any topic of the unit), otherwise
    `strong` (≥ 75), `improving` (40–74), `weak` (< 40).

    Errors: 401 not logged in · 404 `SUBJECT_NOT_FOUND`."""
    return await service.list_subject_units(session, user, subject_id)


@router.get(
    "/units/{unit_id}/topics",
    response_model=UnitTopicsOut,
    summary="Topics of a unit with sub-topics and my progress",
)
async def list_unit_topics(
    unit_id: str, user: CurrentUserDep, session: SessionDep
) -> UnitTopicsOut:
    """`unit_id`: e.g. `u6`. Topics in syllabus order, each with its sub-topics.

    Topic `status`: `not_started` | `in_progress` | `mastered`. `summary` counts my mastered
    and weak topics in the unit.

    Errors: 401 not logged in · 404 `UNIT_NOT_FOUND`."""
    return await service.list_unit_topics(session, user, unit_id)


@router.get(
    "/topics/{topic_id}",
    response_model=TopicDetailOut,
    summary="One topic with its sub-topics and my progress",
)
async def get_topic(topic_id: str, user: CurrentUserDep, session: SessionDep) -> TopicDetailOut:
    """`topic_id`: e.g. `bio-6.1`.

    Errors: 401 not logged in · 404 `TOPIC_NOT_FOUND`."""
    return await service.get_topic(session, user, topic_id)
