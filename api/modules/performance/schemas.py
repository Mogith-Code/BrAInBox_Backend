"""Request / response models (Pydantic) for the performance module. Owner: Keshomigha."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from api.modules.performance.grading import TopicStatus
from api.modules.syllabus.schemas import CamelModel
from shared.enums import MistakeType, TopicProgressStatus


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


# ---------------------------------------------------------------- concept insights
class ConceptPerformance(BaseModel):
    """Score for one concept (a syllabus sub-topic), from answers to questions linked to it."""

    concept_id: uuid.UUID
    code: str | None
    name: str
    topic_id: uuid.UUID
    topic: str
    unit_number: int
    unit: str
    correct: int
    attempted: int
    percent: float
    grade: str
    grade_label: str
    status: TopicStatus
    understanding: str
    reliable: bool  # False while fewer than `min_questions_per_concept` were attempted


class ConceptInsightsResponse(BaseModel):
    concepts: list[ConceptPerformance]  # concepts with answers, weakest first
    weak_concepts: list[str]  # reliable concepts graded S or F, weakest first
    insufficient_data_concepts: list[str]
    min_questions_per_concept: int
    # How many of the student's valid answers were to questions linked to a concept. When this
    # is 0 the list is empty because questions aren't linked yet, not because nothing is weak.
    linked_answers: int
    total_answers: int
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


# ---------------------------------------------------------------- topic progress (camelCase)
class TopicProgressOut(CamelModel):
    """Same fields and meaning as the progress on the Learn topic responses."""

    id: str  # public code, e.g. "bio-6.1" (the UUID when the topic has no code)
    uuid: uuid.UUID
    status: TopicProgressStatus
    progress_pct: int  # 0..100
    is_weak: bool


# ---------------------------------------------------------------- mistake journal
class MistakeOut(BaseModel):
    """One wrong MCQ answer. The question may be gone (deleted later): then its fields are null."""

    id: uuid.UUID
    question_id: uuid.UUID | None
    question: str | None
    your_answer: str | None
    correct_answer: str | None
    explanation: str | None  # the question's stored explanation
    mistake_type: MistakeType
    misconception: MisconceptionOut | None
    correction: str | None  # how to fix the misconception, if one is linked
    topic_id: uuid.UUID | None
    topic: str | None
    topic_number: str | None
    unit_id: uuid.UUID | None
    unit_number: int | None
    unit: str | None
    source: str | None  # where it happened: diagnostic | quiz | exam | practice
    is_resolved: bool
    resolved_at: datetime | None
    created_at: datetime


class MistakeUpdate(BaseModel):
    resolved: bool  # true = the student fixed it ("Fixed" toggle), false = open again


# =========================================================================== admin analytics
# Totals over all students (never one student's data). Admins' own activity is left out.
class DailyCount(BaseModel):
    day: date  # Sri Lanka date
    count: int


class AnalyticsOverview(BaseModel):
    days: int
    since: date
    total_students: int
    new_students: int
    active_students: int  # students with study activity in the period
    active_students_previous: int  # the same number for the period before it
    active_change_percent: float | None  # None when the previous period had no active students
    attempts_completed: int
    mcq_answers: int
    daily_active_students: list[DailyCount]  # one entry per day, oldest first, 0 when none


class UnitAverage(BaseModel):
    unit_id: uuid.UUID
    number: int
    title: str
    average_mastery: float | None  # None = no student has a measurement yet (never 0 %)
    students_assessed: int


class MissedTopic(BaseModel):
    topic_id: uuid.UUID
    topic: str
    topic_number: str
    unit_number: int
    unit: str
    answers: int
    wrong: int
    wrong_percent: float


class CommonMisconception(BaseModel):
    misconception_id: uuid.UUID
    title: str
    times_chosen: int
    students: int


class AnalyticsPerformance(BaseModel):
    days: int
    since: date
    units: list[UnitAverage]  # current level per unit, not limited to the period
    min_answers_per_topic: int  # topics with fewer answers are left out of most_missed_topics
    most_missed_topics: list[MissedTopic]  # highest wrong_percent first
    misconceptions: list[CommonMisconception]  # most chosen first


class AIFeatureUsage(BaseModel):
    feature: str  # the prompt's folder ("notes", "visuals"), else the operation ("embed", "ocr")
    requests: int
    percent: float


class AnalyticsAIUsage(BaseModel):
    days: int
    since: date
    total_requests: int
    images: int
    # None = not recorded. The AI service doesn't log cost or tokens yet, so these aren't 0.
    total_cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    by_feature: list[AIFeatureUsage]  # most used first
    daily_requests: list[DailyCount]  # one entry per day, oldest first, 0 when none
