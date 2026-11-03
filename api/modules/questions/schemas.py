"""Request / response models (Pydantic) for the questions module. Owner: Udith."""

import uuid

from pydantic import BaseModel


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


class QuestionOptionOut(BaseModel):
    """MCQ option displayed to students (correctness hidden)."""

    id: uuid.UUID
    label: str
    text: str


class QuestionDetailOut(BaseModel):
    """A question as shown in practice / question bank (answer key hidden)."""

    id: uuid.UUID
    topic_id: uuid.UUID | None
    question_type: str
    stem: str
    marks: int = 1
    options: list[QuestionOptionOut] = []
    explanation: str | None = None


class TopicPracticeQuestionsOut(BaseModel):
    """Practice questions for a syllabus topic."""

    topic_id: uuid.UUID
    total: int
    questions: list[QuestionDetailOut]


class ExplainQuestionRequest(BaseModel):
    selected_option_id: uuid.UUID | None = None


class ExplainQuestionResponse(BaseModel):
    question_id: uuid.UUID
    explanation: str
