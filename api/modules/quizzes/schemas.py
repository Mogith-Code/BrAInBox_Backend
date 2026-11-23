"""Request / response models (Pydantic) for the quizzes module. Owner: Udith.

Diagnostic test (onboarding): 15 quick MCQs across the 10 units, about 10 minutes.
Correct answers are NEVER sent to the app before the test is submitted.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- start
class OptionOut(BaseModel):
    id: uuid.UUID
    label: str  # "A".."E"
    text: str


class DiagnosticQuestionOut(BaseModel):
    id: uuid.UUID
    unit_code: str  # "6" = Unit 6
    unit_title: str
    stem: str
    options: list[OptionOut]
    selected_option_id: uuid.UUID | None = None  # filled when resuming an unfinished test


class DiagnosticStartOut(BaseModel):
    attempt_id: uuid.UUID
    total: int
    minutes: int
    answered: int  # > 0 when resuming
    questions: list[DiagnosticQuestionOut]


# ---------------------------------------------------------------- answer
class AnswerIn(BaseModel):
    question_id: uuid.UUID
    option_id: uuid.UUID


class AnswerSavedOut(BaseModel):
    saved: bool = True
    answered: int
    total: int


# ---------------------------------------------------------------- result
class UnitRef(BaseModel):
    unit_code: str
    unit_title: str


class UnitResult(BaseModel):
    unit_code: str
    unit_title: str
    mastery: int  # 0-100
    status: Literal["strong", "ok", "needs_work"]


class DiagnosticResult(BaseModel):
    attempt_id: uuid.UUID
    completed_at: datetime
    score: int
    total: int
    strongest: UnitRef
    needs_work: UnitRef
    units: list[UnitResult]
    # Units with no approved questions yet: not measured by this test.
    units_not_checked: list[UnitRef] = []
    summary: str
    summary_ai_generated: bool
    disclaimer: str


class SkippedOut(BaseModel):
    skipped: bool = True


# =========================================================================== quizzes (practice)
class QuizCreate(BaseModel):
    """What to practise. With nothing chosen the quiz covers the whole syllabus."""

    unit: str | None = Field(default=None, description='Unit id, code ("u6") or number ("6")')
    topic: str | None = Field(default=None, description='Topic id or code ("bio-6.1")')
    concept_id: uuid.UUID | None = None
    count: int = Field(default=10, ge=1, le=50)
    difficulty: Literal["easy", "medium", "hard", "mixed"] = "mixed"
    timed: bool = False
    focus_weak: bool = False  # weakest concepts first
    mistakes_only: bool = False  # "practice my mistakes"


class QuizQuestionOut(BaseModel):
    id: uuid.UUID
    position: int  # 1-based
    stem: str
    unit_code: str
    unit_title: str
    topic_id: uuid.UUID
    topic_title: str
    difficulty: str
    options: list[OptionOut]
    # Filled once the question is answered (answers are final: feedback shows the solution).
    selected_option_id: uuid.UUID | None = None
    correct_option_id: uuid.UUID | None = None
    is_correct: bool | None = None
    flagged: bool = False


class QuizOut(BaseModel):
    quiz_id: uuid.UUID
    title: str
    status: str  # in_progress | graded
    total: int
    answered: int
    timed: bool
    time_limit_minutes: int | None
    started_at: datetime
    questions: list[QuizQuestionOut]


class QuizAnswerIn(BaseModel):
    question_id: uuid.UUID
    option_id: uuid.UUID
    time_spent_seconds: int | None = Field(default=None, ge=0, le=7200)


class MisconceptionCard(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    correction: str | None


class ConceptRef(BaseModel):
    id: uuid.UUID
    name: str
    topic_id: uuid.UUID
    topic_title: str


class MasteryChange(BaseModel):
    before: int | None  # 0-100, null = first answer on this concept
    after: int
    level: str  # weak | improving | strong | mastered


class AnswerFeedback(BaseModel):
    """Instant feedback after one answer. No AI call: it comes from the MCQ mapping."""

    question_id: uuid.UUID
    selected_option_id: uuid.UUID
    correct_option_id: uuid.UUID
    is_correct: bool
    explanation: str | None  # the question's explanation
    option_explanation: str | None  # why the chosen option is right / wrong
    misconception: MisconceptionCard | None
    concept: ConceptRef | None
    mastery: MasteryChange | None
    mistake_type: str | None
    recurring_misconception: bool
    recurring_count: int
    answered: int
    total: int


class FlagIn(BaseModel):
    flagged: bool


class TopicAccuracy(BaseModel):
    topic_id: uuid.UUID
    topic: str
    correct: int
    total: int
    percent: int


class MisconceptionCount(BaseModel):
    id: uuid.UUID
    title: str
    correction: str | None
    count: int


class ReviewItem(BaseModel):
    question_id: uuid.UUID
    position: int
    stem: str
    topic: str
    selected: str | None  # "C. text" or null when not answered
    correct: str
    is_correct: bool
    explanation: str | None
    flagged: bool


class QuizResult(BaseModel):
    quiz_id: uuid.UUID
    title: str
    score: int
    total: int
    answered: int
    percent: int
    time_seconds: int
    by_topic: list[TopicAccuracy]
    misconceptions: list[MisconceptionCount]
    review: list[ReviewItem]
    mistakes: int
    disclaimer: str


class QuizBrief(BaseModel):
    quiz_id: uuid.UUID
    title: str
    status: str
    total: int
    score: int | None
    percent: int | None
    started_at: datetime


class PracticeHub(BaseModel):
    """GET /practice/hub: what the Practice tab shows."""

    in_progress: QuizBrief | None
    recent: list[QuizBrief]
    open_mistakes: int
    weak_concepts: int
    approved_questions: int
