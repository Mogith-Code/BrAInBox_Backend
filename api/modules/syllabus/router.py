"""HTTP endpoints for the syllabus module. Owner: Keshomigha.

<<<<<<< Updated upstream
    GET    /api/v1/units                 current units with their topic counts
    GET    /api/v1/units/{id}/topics     one unit and its current topics
    GET    /api/v1/topics/{id}           one topic with its unit and concepts
=======
Implemented (Learn navigation):
    GET    /api/v1/subjects/{subject_id}/units             Units of a subject + my progress
    GET    /api/v1/units/{unit_id}/topics                  Topics of a unit + sub-topics + my progress
    GET    /api/v1/topics/{topic_id}                       One topic with its sub-topics

Ids in the path can be the public code ("biology", "u6", "bio-6.1") or the UUID.

Planned endpoints (details in README.md):
    GET    /api/v1/units                                   All 10 units
>>>>>>> Stashed changes

All need a logged-in user. Lists show the current syllabus only (outdated rows hidden).
Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.syllabus import service
from api.modules.syllabus.schemas import ModuleStatus, TopicDetailOut, UnitOut, UnitTopicsOut

router = APIRouter(tags=["Syllabus"])


@router.get("/syllabus/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
<<<<<<< Updated upstream
    return await service.get_status()


@router.get("/units", response_model=list[UnitOut], summary="All units of the current syllabus")
async def list_units(user: CurrentUserDep, session: SessionDep) -> list[UnitOut]:
    """Unit 1 first. `topic_count` counts current topics only."""
    return await service.get_units(session)
=======
    # TODO(Keshomigha): remove this placeholder once the app no longer calls it.
    return await service.get_status()


@router.get(
    "/subjects/{subject_id}/units",
    response_model=list[UnitOut],
    summary="Units of a subject with my progress",
)
async def list_units(subject_id: str, user: CurrentUserDep, session: SessionDep) -> list[UnitOut]:
    """`subject_id`: e.g. `biology`. Units in syllabus order.

    `progressPct` is the average of my topic scores in the unit (topics I have not started
    count as 0). `status`: `strong` (≥ 75), `improving` (40–74), `weak` (< 40).

    Errors: 401 not logged in · 404 `SUBJECT_NOT_FOUND`."""
    return await service.list_units(session, user, subject_id)
>>>>>>> Stashed changes


@router.get(
    "/units/{unit_id}/topics",
    response_model=UnitTopicsOut,
<<<<<<< Updated upstream
    summary="One unit and its topics",
)
async def list_unit_topics(
    unit_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> UnitTopicsOut:
    """Topics in syllabus order. 404 `UNIT_NOT_FOUND` for an unknown or outdated unit."""
    return await service.get_unit_topics(session, unit_id)
=======
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
>>>>>>> Stashed changes


@router.get(
    "/topics/{topic_id}",
    response_model=TopicDetailOut,
<<<<<<< Updated upstream
    summary="One topic with its concepts",
)
async def get_topic(
    topic_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> TopicDetailOut:
    """Works for outdated topics too (`is_outdated: true`). 404 `TOPIC_NOT_FOUND` if unknown."""
    return await service.get_topic_detail(session, topic_id)
=======
    summary="One topic with its sub-topics and my progress",
)
async def get_topic(topic_id: str, user: CurrentUserDep, session: SessionDep) -> TopicDetailOut:
    """`topic_id`: e.g. `bio-6.1`.

    Errors: 401 not logged in · 404 `TOPIC_NOT_FOUND`."""
    return await service.get_topic(session, user, topic_id)
>>>>>>> Stashed changes
