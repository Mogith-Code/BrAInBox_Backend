"""Admin routes: syllabus manager. Owner: Keshomigha.

Mounted under /api/v1/admin/syllabus by `admin/router.py`, which already
requires the admin role for every route in this file.

    GET    /admin/syllabus/units                        every unit (outdated included)
    POST   /admin/syllabus/units                        add a unit
    PATCH  /admin/syllabus/units/{id}                   edit / mark outdated (no delete)
    GET    /admin/syllabus/units/{id}/topics            every topic of a unit
    POST   /admin/syllabus/units/{id}/topics            add a topic
    PATCH  /admin/syllabus/topics/{id}                  edit / mark outdated
    DELETE /admin/syllabus/topics/{id}                  only when empty and unused
    GET    /admin/syllabus/topics/{id}/concepts         every concept of a topic
    POST   /admin/syllabus/topics/{id}/concepts         add a concept
    PATCH  /admin/syllabus/concepts/{id}                edit / mark outdated
    DELETE /admin/syllabus/concepts/{id}                only when unused

Admin routes call the services of the owning modules (here `api.modules.syllabus.service`);
they do not have their own SQL.
"""

import uuid

from fastapi import APIRouter, Response, status

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.admin.schemas import ModuleStatus
from api.modules.syllabus import service as syllabus_service
from api.modules.syllabus.schemas import (
    AdminConceptOut,
    AdminTopicOut,
    AdminUnitOut,
    ConceptCreate,
    ConceptUpdate,
    TopicCreate,
    TopicUpdate,
    UnitCreate,
    UnitUpdate,
)

router = APIRouter(prefix="/syllabus", tags=["Admin: syllabus"])


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    return ModuleStatus(module="syllabus_admin", status="todo")


# ---------------------------------------------------------------- units


@router.get("/units", response_model=list[AdminUnitOut], summary="All units (outdated included)")
async def list_units(admin: CurrentUserDep, session: SessionDep) -> list[AdminUnitOut]:
    return await syllabus_service.admin_list_units(session)


@router.post(
    "/units",
    response_model=AdminUnitOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a unit",
)
async def create_unit(req: UnitCreate, admin: CurrentUserDep, session: SessionDep) -> AdminUnitOut:
    """409 `UNIT_NUMBER_TAKEN` if the number exists."""
    return await syllabus_service.admin_create_unit(session, req)


@router.patch("/units/{unit_id}", response_model=AdminUnitOut, summary="Edit a unit")
async def update_unit(
    unit_id: uuid.UUID, req: UnitUpdate, admin: CurrentUserDep, session: SessionDep
) -> AdminUnitOut:
    """Send only the fields to change. Units are never deleted: set `is_outdated: true`."""
    return await syllabus_service.admin_update_unit(session, unit_id, req)


# ---------------------------------------------------------------- topics


@router.get(
    "/units/{unit_id}/topics",
    response_model=list[AdminTopicOut],
    summary="All topics of a unit (outdated included)",
)
async def list_topics(
    unit_id: uuid.UUID, admin: CurrentUserDep, session: SessionDep
) -> list[AdminTopicOut]:
    return await syllabus_service.admin_list_topics(session, unit_id)


@router.post(
    "/units/{unit_id}/topics",
    response_model=AdminTopicOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a topic to a unit",
)
async def create_topic(
    unit_id: uuid.UUID, req: TopicCreate, admin: CurrentUserDep, session: SessionDep
) -> AdminTopicOut:
    """409 `TOPIC_NUMBER_TAKEN` if the unit already has this topic number."""
    return await syllabus_service.admin_create_topic(session, unit_id, req)


@router.patch("/topics/{topic_id}", response_model=AdminTopicOut, summary="Edit a topic")
async def update_topic(
    topic_id: uuid.UUID, req: TopicUpdate, admin: CurrentUserDep, session: SessionDep
) -> AdminTopicOut:
    return await syllabus_service.admin_update_topic(session, topic_id, req)


@router.delete(
    "/topics/{topic_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an empty, unused topic",
)
async def delete_topic(topic_id: uuid.UUID, admin: CurrentUserDep, session: SessionDep) -> Response:
    """409 `TOPIC_HAS_CONCEPTS` or `IN_USE`: mark it outdated instead."""
    await syllabus_service.admin_delete_topic(session, topic_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- concepts


@router.get(
    "/topics/{topic_id}/concepts",
    response_model=list[AdminConceptOut],
    summary="All concepts of a topic (outdated included)",
)
async def list_concepts(
    topic_id: uuid.UUID, admin: CurrentUserDep, session: SessionDep
) -> list[AdminConceptOut]:
    return await syllabus_service.admin_list_concepts(session, topic_id)


@router.post(
    "/topics/{topic_id}/concepts",
    response_model=AdminConceptOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a concept to a topic",
)
async def create_concept(
    topic_id: uuid.UUID, req: ConceptCreate, admin: CurrentUserDep, session: SessionDep
) -> AdminConceptOut:
    """409 `CONCEPT_CODE_TAKEN` if another concept has this code."""
    return await syllabus_service.admin_create_concept(session, topic_id, req)


@router.patch("/concepts/{concept_id}", response_model=AdminConceptOut, summary="Edit a concept")
async def update_concept(
    concept_id: uuid.UUID, req: ConceptUpdate, admin: CurrentUserDep, session: SessionDep
) -> AdminConceptOut:
    return await syllabus_service.admin_update_concept(session, concept_id, req)


@router.delete(
    "/concepts/{concept_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unused concept",
)
async def delete_concept(
    concept_id: uuid.UUID, admin: CurrentUserDep, session: SessionDep
) -> Response:
    """409 `IN_USE` if questions, notes or visuals use it: mark it outdated instead."""
    await syllabus_service.admin_delete_concept(session, concept_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
