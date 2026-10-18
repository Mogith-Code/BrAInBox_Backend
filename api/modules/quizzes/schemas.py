"""Request / response models (Pydantic) for the quizzes module. Owner: Udith.

Diagnostic test (onboarding): 15 quick MCQs across the 10 units, about 10 minutes.
Correct answers are NEVER sent to the app before the test is submitted.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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
    summary: str
    summary_ai_generated: bool
    disclaimer: str


class SkippedOut(BaseModel):
    skipped: bool = True
