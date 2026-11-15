"""Request / response models (Pydantic) for the knowledge_base module. Owner: Keshomigha.

Admin model answers (admin/knowledge_admin.py). The admin app only has a placeholder screen
for these yet, so this shape is the proposal it can be built from.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


def clean_keywords(value: list[str]) -> list[str]:
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


class AnswerPointIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    marks: float = Field(default=1, gt=0, le=50)
    keywords: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("keywords")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        return clean_keywords(value)


class ModelAnswerIn(BaseModel):
    question_id: uuid.UUID
    answer_text: str = Field(min_length=1, max_length=20_000)
    source: Literal["marking_scheme", "admin", "ai"] = "admin"
    status: Literal["draft", "approved"] = "draft"
    points: list[AnswerPointIn] = Field(default_factory=list, max_length=30)


class AnswerPointOut(BaseModel):
    id: uuid.UUID
    text: str
    marks: float
    keywords: list[str]


class ModelAnswerOut(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    question_code: str | None = None  # "Q-1042"
    question_stem: str | None = None
    answer_text: str
    total_marks: float  # the sum of the points' marks
    source: str | None = None
    status: str
    points: list[AnswerPointOut]
    updated_at: datetime


class PointKeywordsIn(BaseModel):
    point_id: uuid.UUID
    keywords: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("keywords")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        return clean_keywords(value)


class ModelAnswerKeywordsIn(BaseModel):
    """Replaces the keywords of the listed points (other points keep theirs)."""

    points: list[PointKeywordsIn] = Field(min_length=1, max_length=30)
