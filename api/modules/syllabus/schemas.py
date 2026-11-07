"""Request / response models (Pydantic) for the syllabus module. Owner: Keshomigha.

Learn navigation (Samni) answers in camelCase, as agreed with the Flutter app:
    GET /subjects/{subject_id}/units  -> list[UnitOut]
    GET /units/{unit_id}/topics       -> UnitTopicsOut
    GET /topics/{topic_id}            -> TopicDetailOut

`id` is the public code ("u6", "bio-6.1", "bio-6.1.1") the app navigates with. `uuid` is the
database id other endpoints expect (e.g. `topic_id` of POST /uploads/text or /papers/generate).
"""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from shared.enums import TopicProgressStatus

# Unit status from the average topic score: >= 75 strong, 40..74 improving, < 40 weak.
UnitStatus = Literal["strong", "improving", "weak"]


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- GET /units
class UnitOut(BaseModel):
    """One unit of the current syllabus, e.g. Unit 6 "Genetics"."""

    id: uuid.UUID
    number: int  # 1..10, also the display order
    title: str
    description: str | None = None
    topic_count: int  # current (not outdated) topics only


# ---------------------------------------------------------------- Learn navigation (camelCase)
class CamelModel(BaseModel):
    """Python fields in snake_case, JSON keys in camelCase (`topic_count` -> `topicCount`)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SubtopicOut(CamelModel):
    id: str  # e.g. "bio-6.1.1"
    title: str


class LearnUnitOut(CamelModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "u6",
                    "uuid": "5b0f8a3e-2c1d-4a8e-9f6b-0d2c7e1a4b55",
                    "number": 6,
                    "title": "Genetics",
                    "periods": 22,
                    "icon": "dna",
                    "topicCount": 5,
                    "progressPct": 48,
                    "status": "improving",
                }
            ]
        }
    )

    id: str
    uuid: uuid.UUID
    number: int
    title: str
    periods: int | None
    icon: str | None
    topic_count: int
    progress_pct: int  # average score of the unit's topics for the current student, 0..100
    status: UnitStatus


class TopicOut(CamelModel):
    id: str  # e.g. "bio-6.1"
    uuid: uuid.UUID
    code: str  # e.g. "6.1"
    title: str
    order: int
    status: TopicProgressStatus
    progress_pct: int  # the student's score for this topic, 0..100
    is_weak: bool
    subtopics: list[SubtopicOut]


class UnitTopicsSummary(CamelModel):
    """How many topics of the unit the student has mastered / is weak in."""

    mastered: int
    weak: int


class UnitTopicsOut(CamelModel):
    unit: LearnUnitOut
    summary: UnitTopicsSummary
    topics: list[TopicOut]


class TopicDetailOut(TopicOut):
    # True for a topic removed from the current syllabus. It can still be opened (old notes
    # and questions link to it), so the app can show an "Outdated syllabus" tag.
    is_outdated: bool
    unit_id: str  # e.g. "u6"
    unit_number: int
    unit_title: str


# =========================================================================== admin (/admin/syllabus)
# Admins see EVERYTHING, outdated rows included. Updates are partial (PATCH): send only the
# fields to change. Required fields (number, title, name) cannot be set to null.


class AdminUnitOut(BaseModel):
    id: uuid.UUID
    number: int
    title: str
    description: str | None = None
    exam_weight: float
    is_outdated: bool
    topic_count: int  # all topics, outdated included


class UnitCreate(BaseModel):
    number: int = Field(ge=1, le=99)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    exam_weight: float = Field(default=1.0, gt=0, le=100)


class UnitUpdate(BaseModel):
    number: int | None = Field(default=None, ge=1, le=99)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    exam_weight: float | None = Field(default=None, gt=0, le=100)
    is_outdated: bool | None = None


class AdminTopicOut(BaseModel):
    id: uuid.UUID
    unit_id: uuid.UUID
    number: str
    title: str
    description: str | None = None
    order_index: int
    is_outdated: bool
    concept_count: int  # all concepts, outdated included


class TopicCreate(BaseModel):
    number: str = Field(min_length=1, max_length=20)  # e.g. "6.2"
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    order_index: int = Field(default=0, ge=0)


class TopicUpdate(BaseModel):
    number: str | None = Field(default=None, min_length=1, max_length=20)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    order_index: int | None = Field(default=None, ge=0)
    is_outdated: bool | None = None


class AdminConceptOut(BaseModel):
    id: uuid.UUID
    topic_id: uuid.UUID
    code: str | None = None
    name: str
    description: str | None = None
    learning_outcome: str | None = None
    order_index: int
    is_outdated: bool


class ConceptCreate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=20)  # e.g. "6.2.1"
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    learning_outcome: str | None = None
    order_index: int = Field(default=0, ge=0)


class ConceptUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    learning_outcome: str | None = None
    order_index: int | None = Field(default=None, ge=0)
    is_outdated: bool | None = None
