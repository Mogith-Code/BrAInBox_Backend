"""Request / response models (Pydantic) for the exams module. Owner: Udith.

Paper generation + evaluation models are ported from Udith's original `app/models/schemas.py`.
Options are answered by letter: "A" = first option, "B" = second, ... "E".
"""

import uuid

from pydantic import BaseModel, Field, model_validator


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- generate
class PaperGenerateRequest(BaseModel):
    topic_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    num_questions: int = Field(default=20, ge=1, le=60)
    title: str | None = Field(default=None, max_length=200)


class UnitPaperGenerateRequest(BaseModel):
    units: list[int] = Field(default_factory=list, description="Unit numbers (1..10)")
    unit_numbers: list[int] = Field(default_factory=list, description="Unit numbers (1..10)")
    subject: str = "Biology"
    num_questions: int = Field(default=8, ge=1, le=60)
    title: str | None = Field(default=None, max_length=200)

    model_config = {
        "json_schema_extra": {
            "example": {
                "subject": "Biology",
                "units": [2, 6],
                "num_questions": 8,
                "title": "Model Paper: Units 2 & 6",
            }
        }
    }

    @model_validator(mode="after")
    def unify_units(self) -> "UnitPaperGenerateRequest":
        if not self.unit_numbers and self.units:
            self.unit_numbers = self.units
        elif not self.units and self.unit_numbers:
            self.units = self.unit_numbers
        if not self.unit_numbers:
            raise ValueError("At least one unit must be specified in 'units' or 'unit_numbers'")
        return self


class StudentQuestion(BaseModel):
    """A question as the student sees it (no answer)."""

    id: uuid.UUID
    topic_id: uuid.UUID | None
    topic: str
    question: str
    options: list[str]
    marks: int = 1
    correct_answer: str | None = None  # only filled when DEBUG_SHOW_ANSWERS=true (dev)


class PaperOut(BaseModel):
    paper_id: uuid.UUID
    title: str
    total_questions: int
    questions: list[StudentQuestion]
    warnings: list[str] = []


# ---------------------------------------------------------------- submit / evaluate
class AnswerItem(BaseModel):
    question_id: uuid.UUID
    selected: str | None = None  # "A".."E", None = not answered


class SubmitRequest(BaseModel):
    answers: list[AnswerItem]
    explain: bool = True  # false = skip the AI explanations (faster)


class QuestionResult(BaseModel):
    question_id: uuid.UUID
    topic: str
    question: str
    selected_option: str | None
    correct_answer: str
    is_correct: bool
    marks_awarded: int
    explanation: str | None = None


class TopicScore(BaseModel):
    topic: str
    correct: int
    total: int
    percent: float


class EvaluateResponse(BaseModel):
    paper_id: uuid.UUID
    attempt_id: uuid.UUID | None = None
    total_questions: int
    answered: int
    correct: int
    marks_obtained: int
    marks_total: int
    percent: float
    by_topic: list[TopicScore]
    weak_topics: list[str]
    results: list[QuestionResult]


# TODO(Udith): models for GET /papers, GET /papers/{id}, POST /attempts, GET /attempts/{id}.
