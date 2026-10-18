"""Request / response models (Pydantic) for the recommendations module. Owner: Udith."""

import uuid

from pydantic import BaseModel


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# TODO(Udith): add request/response models for the endpoints in README.md.
#   Use `model_config = ConfigDict(from_attributes=True)` to build them from ORM objects.


class PlanItemOut(BaseModel):
    """One task of today's plan (home screen)."""

    id: uuid.UUID
    kind: str  # "recap" | "practice" | "read"
    title: str
    minutes: int
    unit_label: str | None  # e.g. "Unit 6"
    topic_id: uuid.UUID | None = None
    done: bool
