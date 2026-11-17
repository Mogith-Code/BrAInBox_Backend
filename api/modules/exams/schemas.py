"""Request / response models (Pydantic) for the exams module. Owner: Udith.

Paper generation + evaluation models are ported from Udith's original `app/models/schemas.py`.
Options are answered by letter: "A" = first option, "B" = second, ... "E".
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- generate
class PaperGenerateRequest(BaseModel):
    """Body of the old, synchronous `/exam/generate-paper` (MCQs for some topics)."""

    topic_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    num_questions: int = Field(default=20, ge=1, le=60)
    title: str | None = Field(default=None, max_length=200)


class DifficultyMix(BaseModel):
    """Share of easy / medium / hard questions (any positive numbers; they are normalised)."""

    easy: float = Field(default=0.3, ge=0)
    medium: float = Field(default=0.5, ge=0)
    hard: float = Field(default=0.2, ge=0)

    @model_validator(mode="after")
    def not_all_zero(self) -> "DifficultyMix":
        if self.easy + self.medium + self.hard <= 0:
            raise ValueError("At least one difficulty needs a share above 0")
        return self


class PaperBlueprint(BaseModel):
    """`POST /papers/generate`: what the model paper should contain.

    Scope: `unit_numbers` and/or `topic_ids` (topics win for picking bank questions).
    The old body `{topic_ids, num_questions}` still works: it means `num_questions` MCQs."""

    unit_numbers: list[int] = Field(default_factory=list, max_length=10)
    topic_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    mcq_count: int = Field(default=0, ge=0, le=60)
    structured_count: int = Field(default=0, ge=0, le=10)
    essay_count: int = Field(default=0, ge=0, le=6)
    num_questions: int | None = Field(default=None, ge=1, le=60)  # old body: MCQ count
    difficulty: DifficultyMix = Field(default_factory=DifficultyMix)
    time_limit_minutes: int | None = Field(default=None, ge=10, le=240)
    title: str | None = Field(default=None, max_length=200)

    model_config = {
        "json_schema_extra": {
            "example": {
                "unit_numbers": [2, 6],
                "mcq_count": 20,
                "structured_count": 2,
                "essay_count": 1,
                "difficulty": {"easy": 0.3, "medium": 0.5, "hard": 0.2},
                "time_limit_minutes": 120,
                "title": "Model paper: Units 2 & 6",
            }
        }
    }

    @model_validator(mode="after")
    def check_scope_and_counts(self) -> "PaperBlueprint":
        if not self.unit_numbers and not self.topic_ids:
            raise ValueError("Choose at least one unit (unit_numbers) or topic (topic_ids)")
        if self.mcq_count + self.structured_count + self.essay_count == 0:
            self.mcq_count = self.num_questions or 20
        return self


class PaperJobOut(BaseModel):
    """202 of `POST /papers/generate`. Poll `GET /jobs/{job_id}`; when it succeeded,
    `result.paper_id` is the new paper (`GET /papers/{paper_id}`)."""

    job_id: uuid.UUID
    status: str = "queued"
    from_bank: int  # questions taken from the bank (unseen by this student)
    to_generate: int  # questions the AI writes (the gaps)


# ---------------------------------------------------------------- list / view papers
class PaperSummary(BaseModel):
    id: uuid.UUID
    title: str
    paper_type: str  # past_paper (this list) | ai_generated (my model papers)
    year: int | None
    question_types: list[str]  # mcq / structured / essay
    question_count: int
    outdated_count: int  # questions on an outdated part of the syllabus
    total_marks: int | None
    duration_minutes: int | None


class PaperOption(BaseModel):
    label: str
    text: str


class PaperQuestionOut(BaseModel):
    """A question as the student sees it on a paper (no answer, no marking scheme)."""

    id: uuid.UUID
    position: int
    question_type: str
    topic_id: uuid.UUID | None
    topic: str
    stem: str
    marks: int
    options: list[PaperOption] = []  # MCQs only, A-E
    is_outdated: bool  # the question, its topic or its unit is no longer in the syllabus


class PaperDetail(BaseModel):
    id: uuid.UUID
    title: str
    paper_type: str
    year: int | None
    duration_minutes: int | None
    total_marks: int | None
    question_count: int
    hidden_outdated: int  # left out because of ?hide_outdated=true
    questions: list[PaperQuestionOut]


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
    selected: str | None = None  # MCQs: "A".."E", None = not answered
    answer_text: str | None = Field(default=None, max_length=20_000)  # structured / essay


class SubmitRequest(BaseModel):
    answers: list[AnswerItem]
    explain: bool = True  # false = skip the AI explanations (faster)


class LegacyEvaluateRequest(BaseModel):
    """Body of the old `POST /exam/evaluate` (Udith's standalone exam app): the paper id is in
    the body instead of the URL. Same answers as SubmitRequest."""

    paper_id: uuid.UUID
    answers: list[AnswerItem]
    explain: bool = True


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


class WrittenResult(BaseModel):
    """A structured / essay answer. It is marked in the background by the evaluation module:
    poll `GET /evaluations/{evaluation_id}` for the marks and feedback."""

    question_id: uuid.UUID
    topic: str
    question: str
    question_type: str
    max_marks: int
    # queued = being marked · unanswered = 0 marks · not_markable = no marking scheme yet
    status: Literal["queued", "unanswered", "not_markable"]
    evaluation_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None


class EvaluateResponse(BaseModel):
    """MCQ marks are final at once. `marks_obtained` / `marks_total` / `percent` / `by_topic`
    cover the MCQs; written answers are in `written` and are added to the attempt's score when
    they are marked (`status` "marking" until then, "graded" after)."""

    paper_id: uuid.UUID
    attempt_id: uuid.UUID | None = None
    status: Literal["graded", "marking"] = "graded"
    total_questions: int
    answered: int
    correct: int
    marks_obtained: int
    marks_total: int
    percent: float
    by_topic: list[TopicScore]
    weak_topics: list[str]
    results: list[QuestionResult]
    written: list[WrittenResult] = []
    written_marks_total: int = 0
    pending_written: int = 0
