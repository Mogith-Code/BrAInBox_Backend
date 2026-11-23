"""HTTP endpoints for the quizzes module. Owner: Udith.

Diagnostic test (implemented):
    POST   /api/v1/diagnostic/start                 15 questions (same unfinished test if re-called)
    POST   /api/v1/diagnostic/{attempt_id}/answer   save one answer
    POST   /api/v1/diagnostic/{attempt_id}/submit   mark it -> DiagnosticResult
    POST   /api/v1/diagnostic/skip                  "Skip for now"
    GET    /api/v1/diagnostic/result                latest DiagnosticResult

Quizzes (implemented):
    GET    /api/v1/practice/hub                     Practice tab overview
    POST   /api/v1/quizzes                          Start a quiz (unit / topic / weak areas / mistakes)
    GET    /api/v1/quizzes/{id}                     Quiz with questions and my answers so far
    POST   /api/v1/quizzes/{id}/responses           Answer one question -> instant feedback
    PATCH  /api/v1/quizzes/{id}/questions/{qid}/flag  Flag for review
    POST   /api/v1/quizzes/{id}/submit              Finish -> QuizResult
    GET    /api/v1/quizzes/{id}/result              Score, accuracy by topic, review

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.quizzes import service
from api.modules.quizzes.schemas import (
    AnswerFeedback,
    AnswerIn,
    AnswerSavedOut,
    DiagnosticResult,
    DiagnosticStartOut,
    FlagIn,
    PracticeHub,
    QuizAnswerIn,
    QuizCreate,
    QuizOut,
    QuizResult,
    SkippedOut,
)

router = APIRouter(tags=["Quizzes"])
diagnostic = APIRouter(prefix="/diagnostic", tags=["Diagnostic"])


# ---------------------------------------------------------------- diagnostic


@diagnostic.post(
    "/start", response_model=DiagnosticStartOut, summary="Start (or resume) the diagnostic"
)
async def start(user: CurrentUserDep, session: SessionDep) -> DiagnosticStartOut:
    """15 approved MCQs from every unit that has questions. Correct answers are never included.
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


# ---------------------------------------------------------------- quizzes (practice)
quizzes = APIRouter(prefix="/quizzes", tags=["Quizzes"])


@router.get("/practice/hub", response_model=PracticeHub, summary="What the Practice tab shows")
async def practice_hub(user: CurrentUserDep, session: SessionDep) -> PracticeHub:
    """My unfinished quiz (if any), recent results and how many mistakes I can practise."""
    return await service.practice_hub(session, user.id)


@quizzes.post("", response_model=QuizOut, status_code=201, summary="Start a quiz")
async def start_quiz(req: QuizCreate, user: CurrentUserDep, session: SessionDep) -> QuizOut:
    """Approved MCQs for a unit, topic or concept (or the whole syllabus). `focus_weak` puts my
    weakest concepts first, `mistakes_only` re-asks questions I got wrong. Questions I have not
    seen come first. The correct answers are never included.

    Errors: 404 `UNIT_NOT_FOUND` / `TOPIC_NOT_FOUND` · 422 `NO_QUESTIONS` / `NO_MISTAKES`."""
    return await service.start_quiz(session, user.id, req)


@quizzes.get("/{quiz_id}", response_model=QuizOut, summary="A quiz with my answers so far")
async def get_quiz(quiz_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> QuizOut:
    return await service.get_quiz(session, user.id, quiz_id)


@quizzes.post(
    "/{quiz_id}/responses",
    response_model=AnswerFeedback,
    summary="Answer one question and get instant feedback",
)
async def answer_question(
    quiz_id: uuid.UUID, req: QuizAnswerIn, user: CurrentUserDep, session: SessionDep
) -> AnswerFeedback:
    """Saves the answer, updates the concept's mastery, records a mistake when it is wrong and
    returns the feedback card (correct option, explanation, the misconception behind the chosen
    option). No AI call, so it answers in well under a second.

    Errors: 404 `QUIZ_NOT_FOUND` · 409 `QUIZ_FINISHED` / `ALREADY_ANSWERED` ·
    400 `QUESTION_NOT_IN_QUIZ` / `OPTION_INVALID`."""
    return await service.answer_quiz_question(session, user.id, quiz_id, req)


@quizzes.patch(
    "/{quiz_id}/questions/{question_id}/flag", status_code=204, summary="Flag a question for review"
)
async def flag(
    quiz_id: uuid.UUID,
    question_id: uuid.UUID,
    req: FlagIn,
    user: CurrentUserDep,
    session: SessionDep,
) -> None:
    await service.flag_quiz_question(session, user.id, quiz_id, question_id, req.flagged)


@quizzes.post("/{quiz_id}/submit", response_model=QuizResult, summary="Finish the quiz")
async def submit_quiz(quiz_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> QuizResult:
    """Unanswered questions count as wrong. Safe to call twice."""
    return await service.submit_quiz(session, user.id, quiz_id)


@quizzes.get("/{quiz_id}/result", response_model=QuizResult, summary="Result of a finished quiz")
async def quiz_result(quiz_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> QuizResult:
    """Score, accuracy by topic, misconceptions found and every answer to review.
    409 `QUIZ_NOT_FINISHED` while the quiz is still open."""
    return await service.quiz_result(session, user.id, quiz_id)


router.include_router(quizzes)
