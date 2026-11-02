"""Business logic for the questions module. Owner: Udith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.ai_client import AIClient
from api.core.errors import NotFoundError
from api.modules.questions import repository
from api.modules.questions.schemas import (
    ExplainQuestionResponse,
    ModuleStatus,
    QuestionDetailOut,
    QuestionOptionOut,
    TopicPracticeQuestionsOut,
)
from api.modules.syllabus import service as syllabus_service

MODULE_NAME = "questions"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


async def get_example_questions(
    session: AsyncSession, topic_id: uuid.UUID, limit: int = 3
) -> list[dict[str, Any]]:
    """Approved MCQs shown to the AI as style examples when generating a paper."""
    rows = await repository.random_approved_mcqs(session, topic_id, limit)
    examples = []
    for question, options in rows:
        correct = next((o.text for o in options if o.is_correct), None)
        if correct is not None:
            examples.append(
                {
                    "question": question.stem,
                    "options": [o.text for o in options],
                    "correct_answer": correct,
                }
            )
    return examples


async def get_question(session: AsyncSession, question_id: uuid.UUID) -> QuestionDetailOut:
    """Fetch one question with its MCQ options (correct answer is hidden)."""
    row = await repository.get_by_id(session, question_id)
    if not row:
        raise NotFoundError(f"Question '{question_id}' not found", code="QUESTION_NOT_FOUND")
    question, options = row
    return QuestionDetailOut(
        id=question.id,
        topic_id=question.topic_id,
        question_type=question.question_type,
        stem=question.stem,
        marks=question.marks,
        options=[QuestionOptionOut(id=o.id, label=o.label, text=o.text) for o in options],
        explanation=question.explanation,
    )


async def list_topic_questions(
    session: AsyncSession, topic_id: uuid.UUID, limit: int = 10
) -> TopicPracticeQuestionsOut:
    """Approved practice questions for a topic."""
    # Verify topic exists
    await syllabus_service.get_topics(session, [topic_id])
    rows = await repository.list_by_topic(session, topic_id, limit=limit)
    questions = [
        QuestionDetailOut(
            id=q.id,
            topic_id=q.topic_id,
            question_type=q.question_type,
            stem=q.stem,
            marks=q.marks,
            options=[QuestionOptionOut(id=o.id, label=o.label, text=o.text) for o in options],
            explanation=q.explanation,
        )
        for q, options in rows
    ]
    return TopicPracticeQuestionsOut(topic_id=topic_id, total=len(questions), questions=questions)


async def explain_question(
    session: AsyncSession,
    question_id: uuid.UUID,
    selected_option_id: uuid.UUID | None,
    ai: AIClient,
) -> ExplainQuestionResponse:
    """Explain an MCQ answer using the AI service."""
    row = await repository.get_by_id(session, question_id)
    if not row:
        raise NotFoundError(f"Question '{question_id}' not found", code="QUESTION_NOT_FOUND")
    question, options = row
    correct = next((o.text for o in options if o.is_correct), None) or ""
    selected = next((o.text for o in options if o.id == selected_option_id), None)

    items = [
        {
            "question_id": str(question.id),
            "question": question.stem,
            "correct_answer": correct,
            "selected_option": selected,
        }
    ]
    response = await ai.sync("explain-mcq", {"items": items})
    explanations = response.get("result", {}).get("explanations", {})
    explanation_text = explanations.get(str(question.id), question.explanation or "No explanation available.")
    return ExplainQuestionResponse(question_id=question.id, explanation=explanation_text)

