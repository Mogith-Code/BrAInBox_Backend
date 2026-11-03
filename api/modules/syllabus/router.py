"""HTTP endpoints for the syllabus module. Owner: Keshomigha.

    GET    /api/v1/units                 current units with their topic counts
    GET    /api/v1/units/{id}/topics     one unit and its current topics
    GET    /api/v1/topics/{id}           one topic with its unit and concepts

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
    return await service.get_status()


@router.get("/units", response_model=list[UnitOut], summary="All units of the current syllabus")
async def list_units(user: CurrentUserDep, session: SessionDep) -> list[UnitOut]:
    """Unit 1 first. `topic_count` counts current topics only."""
    return await service.get_units(session)


@router.get(
    "/units/{unit_id}/topics",
    response_model=UnitTopicsOut,
    summary="One unit and its topics",
)
async def list_unit_topics(
    unit_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> UnitTopicsOut:
    """Topics in syllabus order. 404 `UNIT_NOT_FOUND` for an unknown or outdated unit."""
    return await service.get_unit_topics(session, unit_id)


@router.get(
    "/topics/{topic_id}",
    response_model=TopicDetailOut,
    summary="One topic with its concepts",
)
async def get_topic(
    topic_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> TopicDetailOut:
    """Works for outdated topics too (`is_outdated: true`). 404 `TOPIC_NOT_FOUND` if unknown."""
    return await service.get_topic_detail(session, topic_id)
