"""Request / response models (Pydantic) for the community module. Owner: Mogith."""

import uuid

from pydantic import BaseModel


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- groups
class GroupOut(BaseModel):
    """A study group, as the logged-in student sees it."""

    id: uuid.UUID
    slug: str | None  # e.g. "general", "unit-6"
    name: str
    description: str | None = None
    unit_id: uuid.UUID | None = None  # None for groups not tied to a unit (e.g. General)
    is_default: bool  # the "General" group, listed first
    is_private: bool
    member_count: int
    is_member: bool  # has the logged-in student joined?
    my_role: str | None = None  # member | moderator | owner, None when not a member
