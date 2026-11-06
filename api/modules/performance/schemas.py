"""Request / response models (Pydantic) for the performance module. Owner: Keshomigha."""

import uuid
from datetime import date, datetime

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


# ---------------------------------------------------------------- unit insights
class UnitMasteryOut(BaseModel):
    """The student's current mastery of one unit (0-100), from the newest measurement."""

    unit_id: uuid.UUID
    number: int
    title: str
    topic_count: int
    mastery: int | None  # None = never measured (shown as "not assessed", never 0 %)
    grade: str | None
    grade_label: str | None
    status: TopicStatus  # strong .. very_weak, or not_attempted
    understanding: str
    # Change since 7 days ago; None when there is no measurement older than 7 days to compare.
    change_week: int | None
    source: str | None  # what measured it last: diagnostic | practice | exam | quiz
    measured_at: datetime | None


class UnitRank(BaseModel):
    unit_id: uuid.UUID
    number: int
    title: str
    mastery: int


class UnitInsightsResponse(BaseModel):
    units: list[UnitMasteryOut]  # syllabus order (Unit 1 first)
    assessed_units: int
    total_units: int
    average_mastery: float | None  # over assessed units only; None when none is assessed
    strongest: UnitRank | None
    weakest: UnitRank | None
    grade_bands: list[GradeBandOut]
    note: str


# ---------------------------------------------------------------- insights summary
class TopicStatusCounts(BaseModel):
    """How many topics the student is at each level (topics with at least one answer)."""

    strong: int = 0
    good: int = 0
    developing: int = 0
    weak: int = 0
    very_weak: int = 0
    insufficient_data: int = 0  # fewer than min_questions_per_topic valid answers


class InsightsSummaryResponse(BaseModel):
    """The Insights overview: one number per card, all from the student's own data."""

    # Units (same numbers as GET /insights/units)
    overall_mastery: float | None  # average over assessed units; None when none is assessed
    # Average of each unit's own weekly change; None when no unit has a value 7+ days old.
    mastery_change_week: float | None
    units_assessed: int
    total_units: int
    strongest_unit: UnitRank | None
    weakest_unit: UnitRank | None
    # MCQs (same numbers as GET /insights/topics)
    mcq: OverallResult
    attempts_completed: int
    topics: TopicStatusCounts
    weak_topics: list[str]  # reliable topics graded S or F, weakest first
    # Study habit
    streak_days: int
    study_days_last_7: int  # days with study activity in the last 7 days, today included
    last_study_date: date | None
    note: str
