"""Request / response models (Pydantic) for the evaluation module."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DISCLAIMER = "Formative feedback – not an official exam mark."


class WrittenQuestionOut(BaseModel):
    """A structured / essay question that can be checked (it has an approved marking scheme)."""

    id: uuid.UUID
    code: str  # "Q-1042"
    question_type: Literal["structured", "essay"]
    stem: str
    marks: float
    difficulty: str
    year: int | None  # past-paper year
    is_outdated: bool
    topic_id: uuid.UUID | None
    topic_title: str | None
    unit_number: int | None
    my_attempts: int
    my_best_marks: float | None


class AnswerPagesOut(BaseModel):
    """Photos of a handwritten answer, stored and ready for OCR."""

    image_paths: list[str]
    pages: int


class OcrRequest(BaseModel):
    question_id: uuid.UUID
    image_paths: list[str] = Field(min_length=1, max_length=10)


class EvaluationRequest(BaseModel):
    question_id: uuid.UUID
    answer_text: str = Field(min_length=1, max_length=20_000)
    # The evaluation an OCR job created: the corrected text is evaluated on that same row.
    evaluation_id: uuid.UUID | None = None


class EvaluationJobOut(BaseModel):
    """202 Accepted: poll GET /jobs/{job_id}, then read GET /evaluations/{evaluation_id}."""

    evaluation_id: uuid.UUID
    job_id: uuid.UUID
    status: str


class PointResult(BaseModel):
    id: uuid.UUID | None
    text: str
    marks: float
    status: Literal["covered", "partial", "missing"]
    marks_awarded: float
    evidence: str | None  # the part of the answer that matched
    matched_keywords: list[str]
    is_required: bool


class MasteryChangeOut(BaseModel):
    concept: str | None
    before: int | None
    after: int
    level: str


class EvaluationOut(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    question: str
    question_type: str
    # queued/running: OCR or marking is in progress · ocr_ready: check the text, then submit ·
    # succeeded: marked · failed: see `error`
    status: Literal["queued", "running", "ocr_ready", "succeeded", "failed"]
    source: Literal["typed", "handwritten"]
    answer_text: str | None
    ocr_text: str | None
    estimated_marks: float | None
    max_marks: float | None
    percent: int | None
    covered: int
    partial: int
    missing: int
    points: list[PointResult]
    model_answer: str | None  # shown only once the answer is marked
    feedback: str | None
    tips: list[str]
    strengths: list[str]
    tips_ai_generated: bool
    structure_ok: bool | None
    confidence: float | None
    error: str | None
    disclaimer: str = DISCLAIMER
    created_at: datetime


class EvaluationBrief(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    question: str
    status: str
    source: str
    estimated_marks: float | None
    max_marks: float | None
    created_at: datetime


# --------------------------------------------------------------------------- admin
class ManualMarksIn(BaseModel):
    """A teacher's marks for the same answer, for the accuracy report."""

    manual_marks: float = Field(ge=0, le=100)


class AdminEvaluationOut(BaseModel):
    id: uuid.UUID
    question: str
    answer_text: str | None
    estimated_marks: float | None
    max_marks: float | None
    manual_marks: float | None
    difference: float | None  # estimated - manual
    created_at: datetime


class AccuracyReport(BaseModel):
    """Estimated marks against manual marks, over every manually marked evaluation."""

    samples: int
    mean_absolute_error: float | None  # in marks
    within_one_mark: float | None  # share 0..1
    correlation: float | None
    note: str
