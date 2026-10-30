"""Request / response models (Pydantic) for the performance module. Owner: Keshomigha."""

import uuid

from pydantic import BaseModel, ConfigDict

from api.modules.performance.grading import TopicStatus


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- topic insights
class GradeBandOut(BaseModel):
    """One grade boundary, e.g. B = 65 % up to (not including) 75 %."""

    grade: str
    label: str
    min_percent: float
    max_percent: float | None  # exclusive upper bound; None for the top band


class OverallResult(BaseModel):
    """The student's result over every analysed question (a practice indicator, not an
    official exam grade)."""

    correct: int
    attempted: int  # valid answered questions
    unanswered: int
    excluded: int  # answers without a reliable marking result (not counted)
    percent: float | None  # None when nothing was attempted
    grade: str | None
    grade_label: str | None


class TopicPerformance(BaseModel):
    """Score for one Biology topic."""

    topic_id: uuid.UUID | None  # None = questions not linked to a syllabus topic
    topic: str
    topic_number: str | None = None
    unit: str | None = None
    correct: int
    attempted: int
    unanswered: int
    percent: float | None  # None when the topic has no valid answers (never treated as 0 %)
    grade: str | None
    grade_label: str | None
    status: TopicStatus
    understanding: str
    reliable: bool  # False while fewer than `min_questions_per_topic` were attempted


class MisconceptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None = None


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    url: str
    resource_type: str


class ReviewQuestion(BaseModel):
    """A question the student answered wrongly, with the model answer / explanation if stored."""

    question_id: uuid.UUID
    question: str
    model_answer: str | None = None


class TopicFeedback(BaseModel):
    topic_id: uuid.UUID | None
    topic: str
    correct: int
    attempted: int
    percent: float | None
    grade: str | None
    status: TopicStatus
    summary: str  # what the result means
    action: str  # what to revise next
    review_questions: list[ReviewQuestion] = []
    misconceptions: list[MisconceptionOut] = []
    resources: list[ResourceOut] = []


class TopicInsightsResponse(BaseModel):
    attempt_id: uuid.UUID | None  # set when only one attempt was analysed
    attempts_analysed: int
    min_questions_per_topic: int
    overall: OverallResult
    topics: list[TopicPerformance]  # ranked from lowest to highest score
    weak_topics: list[str]  # reliable topics graded S or F, weakest first
    insufficient_data_topics: list[str]
    feedback: list[TopicFeedback]
    grade_bands: list[GradeBandOut]
    note: str
