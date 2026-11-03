"""Request / response models (Pydantic) for the syllabus module. Owner: Keshomigha."""

import uuid

from pydantic import BaseModel, Field


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


# ---------------------------------------------------------------- GET /units/{id}/topics
class TopicOut(BaseModel):
    """One topic in a unit's topic list."""

    id: uuid.UUID
    number: str  # e.g. "6.2"
    title: str
    description: str | None = None
    concept_count: int  # current (not outdated) concepts only


class UnitTopicsOut(BaseModel):
    unit: UnitOut
    topics: list[TopicOut]  # syllabus order


# ---------------------------------------------------------------- GET /topics/{id}
class UnitRef(BaseModel):
    id: uuid.UUID
    number: int
    title: str


class ConceptOut(BaseModel):
    id: uuid.UUID
    code: str | None = None  # e.g. "6.2.1"
    name: str
    description: str | None = None
    learning_outcome: str | None = None


class TopicDetailOut(BaseModel):
    """One topic with its unit and concepts."""

    id: uuid.UUID
    number: str
    title: str
    description: str | None = None
    # True for a topic removed from the current syllabus. It can still be opened (old notes
    # and questions link to it), so the app can show an "Outdated syllabus" tag.
    is_outdated: bool
    unit: UnitRef
    concepts: list[ConceptOut]  # current concepts, syllabus order


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
