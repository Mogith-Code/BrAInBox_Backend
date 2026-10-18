"""Request / response models (Pydantic) for the recommendations module. Owner: Udith."""

from pydantic import BaseModel


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# TODO(Udith): add request/response models for the endpoints in README.md.
#   Use `model_config = ConfigDict(from_attributes=True)` to build them from ORM objects.
