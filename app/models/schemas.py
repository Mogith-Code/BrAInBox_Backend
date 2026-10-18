from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class Question(BaseModel):
    id: str
    topic: str
    unit: str
    question: str
    options: List[str] = Field(min_length=4, max_length=5)
    correct_answer: str
    marks: int = 1
    year: Optional[int] = None      # past paper year (or null)

    @model_validator(mode="after")
    def answer_must_be_in_options(self):
        if self.correct_answer not in self.options:
            raise ValueError(
                f"correct_answer '{self.correct_answer}' is not in options (id={self.id})"
            )
        return self


# ---------- generate ----------
class ExamRequest(BaseModel):
    subject: str = "Biology"
    topic: str
    num_questions: int = Field(default=5, ge=1, le=50)


class ExamResponse(BaseModel):
    subject: str
    topic: str
    questions: List[Question]


class PaperRequest(BaseModel):
    subject: str = "Biology"
    topics: List[str] = Field(min_length=1, max_length=10)
    num_questions: int = Field(default=20, ge=1, le=60)


class StudentQuestion(BaseModel):
    id: str
    topic: str
    unit: str
    question: str
    options: List[str]
    marks: int = 1
    correct_answer: Optional[str] = None     # filled only when DEBUG_SHOW_ANSWERS=true


class PaperResponse(BaseModel):
    paper_id: str
    subject: str
    topics: List[str]
    total_questions: int
    questions: List[StudentQuestion]
    warnings: List[str] = []

# ---------- evaluate ----------
class AnswerItem(BaseModel):
    question_id: str
    selected: Optional[str] = None      # "A".."E", null = not answered


class EvaluateRequest(BaseModel):
    paper_id: str
    answers: List[AnswerItem]


class QuestionResult(BaseModel):
    question_id: str
    topic: str
    question: str
    selected_option: Optional[str]
    correct_answer: str
    is_correct: bool
    marks_awarded: int
    explanation: Optional[str] = None


class TopicScore(BaseModel):
    topic: str
    correct: int
    total: int
    percent: float


class EvaluateResponse(BaseModel):
    paper_id: str
    total_questions: int
    answered: int
    correct: int
    marks_obtained: int
    marks_total: int
    percent: float
    by_topic: List[TopicScore]
    weak_topics: List[str]
    results: List[QuestionResult]

class EvaluateRequest(BaseModel):
    paper_id: str
    answers: List[AnswerItem]
    explain: bool = True        # set false to skip AI explanations