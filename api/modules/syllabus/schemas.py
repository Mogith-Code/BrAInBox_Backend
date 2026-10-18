"""Request / response models (Pydantic) for the syllabus module. Owner: Keshomigha."""

from pydantic import BaseModel


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# TODO(Keshomigha): add request/response models for the endpoints in README.md.
#   Use `model_config = ConfigDict(from_attributes=True)` to build them from ORM objects.
