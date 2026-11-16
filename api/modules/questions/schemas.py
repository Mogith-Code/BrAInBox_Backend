"""Request / response models (Pydantic) for the questions module. Owner: Udith."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


# ---------------------------------------------------------------- admin: question bank + editor
# Matches BrAInBox_Mobile apps/admin/lib/features/question_bank/domain/question_bank_models.dart
QuestionKind = Literal["mcq", "structured", "essay"]
DifficultyValue = Literal["easy", "medium", "hard"]
# "outdated" is shown for a question an admin marked outdated (whatever its status was).
AdminQuestionStatus = Literal[
    "draft", "pending_review", "approved", "rejected", "archived", "outdated"
]
OptionLabel = Literal["A", "B", "C", "D", "E"]


class AdminQuestionRow(BaseModel):
    id: uuid.UUID
    code: str  # "Q-4821"
    stem: str
    unit_number: int | None = None
    topic_title: str | None = None
    type: QuestionKind
    difficulty: DifficultyValue
    source_year: int | None = None  # past-paper year
    is_ai_generated: bool
    status: AdminQuestionStatus


class AdminQuestionPage(BaseModel):
    items: list[AdminQuestionRow]
    total: int
    past_paper_percent: int  # 0-100, of the questions matching the filters


class BulkQuestionsIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    action: Literal["approve", "mark_outdated", "delete"]


class AdminOption(BaseModel):
    label: OptionLabel
    text: str = Field(default="", max_length=2000)
    is_correct: bool = False
    misconception: str | None = Field(default=None, max_length=200)  # why a student picks it


class AdminQuestionIn(BaseModel):
    """Body of POST / PUT /admin/questions. Publishing = `status: "approved"`."""

    stem: str = Field(min_length=1, max_length=5000)
    type: QuestionKind = "mcq"
    difficulty: DifficultyValue = "medium"
    unit_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    concept_id: uuid.UUID | None = None
    explanation: str | None = Field(default="", max_length=5000)
    status: Literal["draft", "pending_review", "approved", "rejected"] = "draft"
    is_ai_generated: bool = False
    options: list[AdminOption] = Field(default_factory=list, max_length=5)

    @field_validator("options")
    @classmethod
    def unique_labels(cls, value: list[AdminOption]) -> list[AdminOption]:
        labels = [o.label for o in value]
        if len(labels) != len(set(labels)):
            raise ValueError("each option label (A-E) may be used once")
        return sorted(value, key=lambda o: o.label)


class AdminQuestionOut(BaseModel):
    id: uuid.UUID
    code: str
    stem: str
    type: QuestionKind
    difficulty: DifficultyValue
    unit_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    concept_id: uuid.UUID | None = None
    explanation: str
    status: AdminQuestionStatus
    is_ai_generated: bool
    options: list[AdminOption]


# ---------------------------------------------------------------- admin: past papers
# Matches BrAInBox_Mobile apps/admin/lib/features/past_papers/domain/past_papers_models.dart
PaperType = Literal["paper_1_mcq", "paper_2_structured"]
ExtractionState = Literal["done", "running", "low_confidence", "failed"]


class PastPaperOut(BaseModel):
    id: uuid.UUID
    year: int
    paper_type: PaperType
    scheme_linked: bool  # a marking scheme PDF was uploaded with it
    extraction: ExtractionState
    questions_extracted: int
    progress: float  # 0-1
    low_confidence: int  # questions whose text may be misread (ocr_confidence < 0.8)
    outdated_syllabus: bool


class PastPaperQuestionOut(BaseModel):
    id: uuid.UUID
    label: str  # "Q3 (b)"
    marks: int | None = None
    text: str
    ocr_confidence: float | None = None
    model_answer: str | None = None
    keywords: list[str]
    suggested_keywords: list[str]


class PastPaperAnswerIn(BaseModel):
    model_answer: str | None = Field(default=None, max_length=10_000)
    keywords: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, value: list[str]) -> list[str]:
        """Trimmed, no empty ones, no repeats (any case), each at most 100 characters."""
        seen: set[str] = set()
        out = []
        for word in value:
            word = " ".join(word.split())
            if len(word) > 100:
                raise ValueError("a keyword can have at most 100 characters")
            if word and word.lower() not in seen:
                seen.add(word.lower())
                out.append(word)
        return out


# ---------------------------------------------------------------- admin: MCQ -> misconception mapping
class OptionMisconceptionIn(BaseModel):
    """`null` (or "") removes the link."""

    misconception: str | None = Field(default=None, max_length=200)


class OptionMisconceptionOut(BaseModel):
    option_id: uuid.UUID
    question_id: uuid.UUID
    question_code: str
    label: str
    text: str
    is_correct: bool
    misconception: str | None = None
