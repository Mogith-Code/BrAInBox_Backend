"""Admin routes: knowledge base (model answers). Owner: Keshomigha.

Mounted under /api/v1/admin by `admin/router.py`, which already requires the admin role.

    GET  /admin/model-answers                       ?question_id=&status=
    POST /admin/model-answers                       a model answer with its marking points
    PUT  /admin/model-answers/{answer_id}/keywords  replace the keywords of some points

The admin app has a placeholder screen for these; the shapes are documented in
docs/api-endpoints.md. Admin routes call the services of the owning modules (here
`api.modules.knowledge_base.service`); they do not have their own SQL.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, status

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.admin import service as admin_service
from api.modules.admin.schemas import ModuleStatus
from api.modules.knowledge_base import service as knowledge_service
from api.modules.knowledge_base.schemas import ModelAnswerIn, ModelAnswerKeywordsIn, ModelAnswerOut

router = APIRouter(tags=["Admin: knowledge base"])


@router.get(
    "/knowledge/status", response_model=ModuleStatus, summary="Placeholder: admin area status"
)
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    return ModuleStatus(module="knowledge_admin", status="todo")


@router.get("/model-answers", response_model=list[ModelAnswerOut], summary="Model answers")
async def list_model_answers(
    admin: CurrentUserDep,
    session: SessionDep,
    question_id: uuid.UUID | None = None,
    status: Literal["draft", "pending_review", "approved", "rejected", "archived"] | None = None,  # noqa: A002
) -> list[ModelAnswerOut]:
    """Last changed first (max 200), each with its marking points and their keywords."""
    return await knowledge_service.admin_list_model_answers(session, question_id, status)


@router.post(
    "/model-answers",
    response_model=ModelAnswerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a model answer with its marking points",
)
async def create_model_answer(
    req: ModelAnswerIn, admin: CurrentUserDep, session: SessionDep
) -> ModelAnswerOut:
    """`total_marks` is the sum of the points' marks.
    Errors: 404 `QUESTION_NOT_FOUND` · 409 `MODEL_ANSWER_EXISTS` · 422."""
    answer = await knowledge_service.admin_create_model_answer(session, admin.id, req)
    await admin_service.record_audit(
        session, admin, "model_answer.create", "model_answer", answer.id
    )
    return answer


@router.put(
    "/model-answers/{answer_id}/keywords",
    response_model=ModelAnswerOut,
    summary="Replace the keywords of marking points",
)
async def set_keywords(
    answer_id: uuid.UUID, req: ModelAnswerKeywordsIn, admin: CurrentUserDep, session: SessionDep
) -> ModelAnswerOut:
    """Errors: 404 `MODEL_ANSWER_NOT_FOUND` · 422 `POINT_NOT_IN_ANSWER` / `VALIDATION_ERROR`."""
    answer = await knowledge_service.admin_set_keywords(session, answer_id, req)
    await admin_service.record_audit(
        session, admin, "model_answer.keywords", "model_answer", answer_id
    )
    return answer
