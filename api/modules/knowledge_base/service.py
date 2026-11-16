"""Business logic for the knowledge_base module. Owner: Keshomigha.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.core.errors import AppError, ConflictError, NotFoundError
from api.modules.knowledge_base import repository
from api.modules.knowledge_base.schemas import (
    AnswerPointOut,
    ModelAnswerIn,
    ModelAnswerKeywordsIn,
    ModelAnswerOut,
    ModuleStatus,
)
from api.modules.questions import service as questions_service
from shared.db.models import AnswerPoint, ModelAnswer
from shared.enums import ContentStatus

MODULE_NAME = "knowledge_base"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Keshomigha): get_marking_scheme(question_id) -> model answer + points + keywords


# =========================================================================== admin: model answers
# Used by admin/knowledge_admin.py: a model answer -> marking points -> keywords per point.

LIST_LIMIT = 200


async def _outs(session: AsyncSession, answers: list[ModelAnswer]) -> list[ModelAnswerOut]:
    points = await repository.points_with_keywords(session, [a.id for a in answers])
    briefs = await questions_service.question_briefs(session, [a.question_id for a in answers])
    out = []
    for answer in answers:
        code, stem = briefs.get(answer.question_id, (None, None))
        out.append(
            ModelAnswerOut(
                id=answer.id,
                question_id=answer.question_id,
                question_code=code,
                question_stem=stem,
                answer_text=answer.answer_text,
                total_marks=answer.total_marks,
                source=answer.source,
                status=answer.status.value,
                points=[
                    AnswerPointOut(id=p.id, text=p.point_text, marks=p.marks, keywords=k)
                    for p, k in points[answer.id]
                ],
                updated_at=answer.updated_at,
            )
        )
    return out


async def admin_list_model_answers(
    session: AsyncSession, question_id: uuid.UUID | None, status: str | None
) -> list[ModelAnswerOut]:
    rows = await repository.list_model_answers(session, question_id, status, LIST_LIMIT)
    return await _outs(session, rows)


async def admin_create_model_answer(
    session: AsyncSession, admin_id: uuid.UUID, req: ModelAnswerIn
) -> ModelAnswerOut:
    """404 QUESTION_NOT_FOUND · 409 MODEL_ANSWER_EXISTS (one per question)."""
    if not await questions_service.question_briefs(session, [req.question_id]):
        raise NotFoundError(f"Question '{req.question_id}' not found", code="QUESTION_NOT_FOUND")
    if await repository.answer_for_question(session, req.question_id) is not None:
        raise ConflictError("This question already has a model answer", code="MODEL_ANSWER_EXISTS")
    now = clock.now()
    answer = ModelAnswer(
        id=uuid.uuid4(),
        question_id=req.question_id,
        answer_text=req.answer_text.strip(),
        total_marks=float(sum(p.marks for p in req.points)),
        source=req.source,
        status=ContentStatus(req.status),
        created_by=admin_id,
        approved_by=admin_id if req.status == "approved" else None,
        approved_at=now if req.status == "approved" else None,
        updated_at=now,
    )
    await repository.add(session, answer)
    for n, point in enumerate(req.points):
        row = AnswerPoint(
            id=uuid.uuid4(),
            model_answer_id=answer.id,
            point_text=point.text.strip(),
            marks=point.marks,
            order_index=n,
        )
        await repository.add(session, row)
        await repository.replace_keywords(session, row.id, point.keywords)
    await session.commit()
    return (await _outs(session, [answer]))[0]


async def admin_set_keywords(
    session: AsyncSession, answer_id: uuid.UUID, req: ModelAnswerKeywordsIn
) -> ModelAnswerOut:
    """Replace the keywords of some points. 404 MODEL_ANSWER_NOT_FOUND · 422 POINT_NOT_IN_ANSWER."""
    answer = await repository.get_model_answer(session, answer_id)
    if answer is None:
        raise NotFoundError("Model answer not found", code="MODEL_ANSWER_NOT_FOUND")
    own = {
        p.id for p, _ in (await repository.points_with_keywords(session, [answer.id]))[answer.id]
    }
    foreign = [str(p.point_id) for p in req.points if p.point_id not in own]
    if foreign:
        raise AppError(
            "These points are not part of this model answer: " + ", ".join(foreign),
            code="POINT_NOT_IN_ANSWER",
            status_code=422,
        )
    for point in req.points:
        await repository.replace_keywords(session, point.point_id, point.keywords)
    answer.updated_at = clock.now()
    await session.commit()
    return (await _outs(session, [answer]))[0]
