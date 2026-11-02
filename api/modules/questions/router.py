"""HTTP endpoints for the questions module. Owner: Udith.

Planned endpoints (details in README.md):
    GET    /api/v1/questions/{id}                          One question with options (no answer key)
    GET    /api/v1/topics/{id}/questions                   Practice questions for a topic
    POST   /api/v1/questions/{id}/explain                  Explain an MCQ answer (sync AI call)

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

import uuid

from fastapi import APIRouter

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.questions import service
from api.modules.questions.schemas import (
    ExplainQuestionRequest,
    ExplainQuestionResponse,
    ModuleStatus,
    QuestionDetailOut,
    TopicPracticeQuestionsOut,
)

router = APIRouter(tags=["Questions"])


@router.get("/questions/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    return await service.get_status()


@router.get(
    "/questions/{question_id}",
    response_model=QuestionDetailOut,
    summary="Get one question with its options (answer hidden)",
)
async def get_question(
    question_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> QuestionDetailOut:
    """Fetch one question with its options for student practice."""
    return await service.get_question(session, question_id)


@router.get(
    "/topics/{topic_id}/questions",
    response_model=TopicPracticeQuestionsOut,
    summary="Practice questions for a syllabus topic",
)
async def list_topic_questions(
    topic_id: uuid.UUID,
    user: CurrentUserDep,
    session: SessionDep,
    limit: int = 10,
) -> TopicPracticeQuestionsOut:
    """Approved practice questions for a topic from the question bank."""
    return await service.list_topic_questions(session, topic_id, limit=limit)


@router.post(
    "/questions/{question_id}/explain",
    response_model=ExplainQuestionResponse,
    summary="Explain an MCQ answer using the AI service",
)
async def explain_question(
    question_id: uuid.UUID,
    req: ExplainQuestionRequest,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
) -> ExplainQuestionResponse:
    """Get an AI explanation for why the correct answer is right and why the chosen option is wrong."""
    return await service.explain_question(session, question_id, req.selected_option_id, ai)

