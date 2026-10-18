"""HTTP endpoints for the exams module. Owner: Udith.

Implemented (ported from Udith's original `/exam/*` routes):
    POST   /api/v1/papers/generate                         Generate an AI model paper (BUILD_PAPER)
    POST   /api/v1/papers/{id}/submit                      Mark answers + explanations, save attempt

Planned (details in README.md):
    GET    /api/v1/papers                                  List papers
    GET    /api/v1/papers/{id}                             One paper
    POST   /api/v1/attempts                                Start an attempt
    GET    /api/v1/attempts/{id}                           Attempt with answers

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.exams import service
from api.modules.exams.schemas import (
    EvaluateResponse,
    ModuleStatus,
    PaperGenerateRequest,
    PaperOut,
    SubmitRequest,
)

router = APIRouter(tags=["Exams"])


@router.get("/exams/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    return await service.get_status()


@router.post(
    "/papers/generate",
    response_model=PaperOut,
    response_model_exclude_none=True,
    summary="Generate an AI model paper from syllabus topics",
)
async def generate_paper(
    req: PaperGenerateRequest, user: CurrentUserDep, session: SessionDep, ai: AIClientDep
) -> PaperOut:
    """Questions are split evenly across the topics and grounded in the approved syllabus
    sources. Answers are never returned (except with DEBUG_SHOW_ANSWERS in dev)."""
    return await service.generate_paper(session, user, req, ai)


@router.post(
    "/papers/{paper_id}/submit",
    response_model=EvaluateResponse,
    summary="Submit answers: marks, score per topic, weak topics and explanations",
)
async def submit_paper(
    paper_id: uuid.UUID,
    req: SubmitRequest,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
) -> EvaluateResponse:
    """Answers use letters ("A".."E"); a missing or invalid letter counts as not answered."""
    return await service.submit_paper(session, user, paper_id, req, ai)
