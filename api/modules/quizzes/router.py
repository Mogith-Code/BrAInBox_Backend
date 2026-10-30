"""HTTP endpoints for the quizzes module. Owner: Udith.

Diagnostic test (implemented):
    POST   /api/v1/diagnostic/start                 15 questions (same unfinished test if re-called)
    POST   /api/v1/diagnostic/{attempt_id}/answer   save one answer
    POST   /api/v1/diagnostic/{attempt_id}/submit   mark it -> DiagnosticResult
    POST   /api/v1/diagnostic/skip                  "Skip for now"
    GET    /api/v1/diagnostic/result                latest DiagnosticResult

Planned (details in README.md):
    POST   /api/v1/quizzes                          Start a quiz for a topic/unit
    GET    /api/v1/quizzes/{id}                     Quiz with questions
    POST   /api/v1/quizzes/{id}/responses           Submit answers
    GET    /api/v1/quizzes/{id}/results             Score + explanations

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.quizzes import service
from api.modules.quizzes.schemas import (
    AnswerIn,
    AnswerSavedOut,
    DiagnosticResult,
    DiagnosticStartOut,
    ModuleStatus,
    SkippedOut,
)

router = APIRouter(tags=["Quizzes"])
diagnostic = APIRouter(prefix="/diagnostic", tags=["Diagnostic"])


@router.get("/quizzes/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    return await service.get_status()


# ---------------------------------------------------------------- diagnostic


@diagnostic.post(
    "/start", response_model=DiagnosticStartOut, summary="Start (or resume) the diagnostic"
)
async def start(user: CurrentUserDep, session: SessionDep) -> DiagnosticStartOut:
    """15 approved MCQs covering all 10 units. Correct answers are never included.
    Calling it again returns the same unfinished test (with `selected_option_id` filled)."""
    return await service.start_diagnostic(session, user.id)


@diagnostic.post("/skip", response_model=SkippedOut, summary="Skip the diagnostic for now")
async def skip(user: CurrentUserDep, session: SessionDep) -> SkippedOut:
    await service.skip_diagnostic(session, user.id)
    return SkippedOut()


@diagnostic.get("/result", response_model=DiagnosticResult, summary="My latest diagnostic result")
async def result(user: CurrentUserDep, session: SessionDep) -> DiagnosticResult:
    return await service.latest_result(session, user.id)


@diagnostic.post(
    "/{attempt_id}/answer", response_model=AnswerSavedOut, summary="Save one diagnostic answer"
)
async def answer(
    attempt_id: uuid.UUID, req: AnswerIn, user: CurrentUserDep, session: SessionDep
) -> AnswerSavedOut:
    return await service.save_answer(session, user.id, attempt_id, req.question_id, req.option_id)


@diagnostic.post(
    "/{attempt_id}/submit",
    response_model=DiagnosticResult,
    summary="Submit and see my starting point",
)
async def submit(
    attempt_id: uuid.UUID, user: CurrentUserDep, session: SessionDep, ai: AIClientDep
) -> DiagnosticResult:
    return await service.submit_diagnostic(session, user.id, attempt_id, ai)


router.include_router(diagnostic)
