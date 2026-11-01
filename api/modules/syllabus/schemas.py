"""Request / response models (Pydantic) for the syllabus module. Owner: Keshomigha."""

import uuid

from pydantic import BaseModel


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
