"""Request / response models shared by the admin route files.

Area-specific admin schemas can live here or in the owning module's schemas.py.
"""

from pydantic import BaseModel


class ModuleStatus(BaseModel):
    """Response of the placeholder status routes."""

    module: str
    status: str


# TODO(each admin area owner): add admin request/response models here, e.g.
#   class QuestionReviewIn(BaseModel): verdict: str; comments: str | None = None   # Udith
