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


class TagPostRequest(BaseModel):
    title: str
    body: str


class KeywordScoreRequest(BaseModel):
    answer_text: str
    question_id: str


class SyncResponse(BaseModel):
    name: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
