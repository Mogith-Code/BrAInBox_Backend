"""Request / response models (Pydantic) for the recommendations module."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ModuleStatus(BaseModel):
    module: str
    status: str


class PlanItemOut(BaseModel):
    """One task of today's plan (home screen)."""

    id: uuid.UUID
    kind: str  # "recap" | "practice" | "read"
    title: str
    minutes: int
    unit_label: str | None  # e.g. "Unit 6"
    topic_id: uuid.UUID | None = None
    done: bool


# --------------------------------------------------------------------------- recommendations
class ResourceOut(BaseModel):
    id: uuid.UUID
    title: str
    url: str
    channel: str | None
    thumbnail_url: str | None
    duration_seconds: int | None


class RecommendationOut(BaseModel):
    """One next step. `reason` always says why it was given (the rules are explainable)."""

    id: uuid.UUID
    # revise_note | practice_quiz | watch_video | retry_answer | reassess | view_visual
    action: str
    title: str
    reason: str
    priority: int  # 1 = do this first ... 5
    score: float  # (1 - mastery) x recency x past-paper weight x 1.5 if recurring
    estimated_minutes: int
    status: str
    concept_id: uuid.UUID | None
    concept: str | None
    topic_id: uuid.UUID | None
    topic: str | None
    unit_number: int | None
    mastery: int | None  # 0-100, the concept's mastery when this was suggested
    # What the app opens, e.g. {"concept_id": "...", "count": 10} for a quiz
    target: dict[str, Any]
    resource: ResourceOut | None = None
    created_at: datetime


class RecommendationList(BaseModel):
    items: list[RecommendationOut]
    # Shown when the list is empty: what to do to get recommendations.
    hint: str | None = None


class RecommendationUpdate(BaseModel):
    status: Literal["in_progress", "done", "dismissed"]


class ReassessmentOutcome(BaseModel):
    """Before / after of a reassessment (or any recommendation tied to a concept)."""

    recommendation_id: uuid.UUID
    concept: str | None
    before: int | None  # 0-100
    after: int | None
    change: int | None
    improved: bool
    level: str
    message: str


# --------------------------------------------------------------------------- study plan
class StudyPlanItemOut(BaseModel):
    id: uuid.UUID
    action: str | None
    title: str
    date: date | None
    estimated_minutes: int | None
    is_done: bool
    order: int
    concept_id: uuid.UUID | None
    topic_id: uuid.UUID | None
    recommendation_id: uuid.UUID | None
    target: dict[str, Any]


class StudyPlanDay(BaseModel):
    date: date
    weekday: str  # "mon".."sun"
    is_study_day: bool
    minutes_planned: int
    minutes_available: int
    items: list[StudyPlanItemOut]


class StudyPlanOut(BaseModel):
    id: uuid.UUID | None  # null when there is nothing to plan yet
    title: str
    start_date: date | None
    end_date: date | None
    done: int
    total: int
    days: list[StudyPlanDay]
    hint: str | None = None


class PlanItemUpdate(BaseModel):
    is_done: bool | None = None


class PlanOrderIn(BaseModel):
    """The ids of ONE day's items in their new order."""

    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
