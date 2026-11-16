"""HTTP schemas for POST /jobs/run and the /sync/* routes."""

from typing import Any

from pydantic import BaseModel, Field

from shared.enums import JobType


class JobRunRequest(BaseModel):
    job_id: str
    job_type: JobType
    payload: dict[str, Any] = Field(default_factory=dict)


class JobRunResponse(BaseModel):
    job_id: str
    job_type: JobType
    result: dict[str, Any]


class ExplainItem(BaseModel):
    question_id: str
    question: str
    correct_answer: str
    selected_option: str | None = None  # option text the student chose, None = not answered


class ExplainMCQRequest(BaseModel):
    items: list[ExplainItem] = Field(max_length=60)


class TopicChoice(BaseModel):
    id: str
    title: str
    unit_number: int | None = None


class TagPostRequest(BaseModel):
    title: str
    body: str
    topics: list[TopicChoice] = Field(default_factory=list, max_length=300)


class ModerateRequest(BaseModel):
    title: str = ""
    body: str


class ResourceCandidate(BaseModel):
    id: str
    title: str
    description: str = ""


class RankResourcesRequest(BaseModel):
    concept: str
    topic: str | None = None
    candidates: list[ResourceCandidate] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=2, ge=1, le=10)


class KeywordScoreRequest(BaseModel):
    answer_text: str
    question_id: str | None = None
    keywords: list[str] = Field(default_factory=list, max_length=200)


class UnitScore(BaseModel):
    unit_code: str
    unit_title: str
    mastery: int = Field(ge=0, le=100)
    status: str


class UnitRefIn(BaseModel):
    unit_code: str
    unit_title: str


class DiagnosticSummaryRequest(BaseModel):
    score: int
    total: int
    strongest: UnitRefIn
    needs_work: UnitRefIn
    units: list[UnitScore] = Field(max_length=20)


class NextActionRequest(BaseModel):
    unit_code: str
    unit_title: str
    topic_title: str | None = None
    mastery: int = Field(ge=0, le=100)


class SyncResponse(BaseModel):
    name: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
