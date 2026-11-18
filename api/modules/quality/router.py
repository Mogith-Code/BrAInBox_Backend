"""HTTP endpoints for the quality module. Owner: Udith.

Planned endpoints (details in README.md):
    POST   /api/v1/questions/{id}/report                   Report a wrong question
    (service) Review-queue logic used by admin/questions_admin.py

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.quality import service
from api.modules.quality.schemas import QuestionReportIn, QuestionReportOut

router = APIRouter(tags=["Quality"])


@router.post(
    "/questions/{question_id}/report",
    response_model=QuestionReportOut,
    status_code=201,
    summary="Report a wrong or unclear question",
)
async def report_question(
    question_id: uuid.UUID, req: QuestionReportIn, user: CurrentUserDep, session: SessionDep
) -> QuestionReportOut:
    """One open report per student and question (409 `ALREADY_REPORTED`). When 3 students have
    reported a question it goes back to admin review and leaves the quizzes."""
    return await service.report_question(session, user, question_id, req)
