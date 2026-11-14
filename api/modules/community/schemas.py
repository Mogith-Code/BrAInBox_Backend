"""Request / response models (Pydantic) for the community module. Owner: Mogith."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from shared.enums import ModerationStatus

MAX_TAGS = 5


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


# ---------------------------------------------------------------- posts
def _clean_tags(tags: list[str] | None) -> list[str] | None:
    """Lower-case, trimmed, no empties or duplicates, order kept."""
    if tags is None:
        return None
    cleaned: list[str] = []
    for tag in tags:
        tag = tag.strip().lower()
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned


class PostCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)  # markdown
    topic_id: uuid.UUID | None = None  # must belong to the group's unit, if the group has one
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    is_question: bool = True

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        if any(len(t.strip()) > 50 for t in value):
            raise ValueError("a tag can have at most 50 characters")
        return _clean_tags(value) or []


class PostUpdate(BaseModel):
    """Send only the fields to change. `topic_id: null` removes the topic."""

    title: str | None = Field(default=None, min_length=3, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=10_000)
    topic_id: uuid.UUID | None = None
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(len(t.strip()) > 50 for t in value):
            raise ValueError("a tag can have at most 50 characters")
        return _clean_tags(value)


class AuthorOut(BaseModel):
    id: uuid.UUID
    name: str  # display name; "Student" when the account has none


class PostOut(BaseModel):
    """A post in a feed (no replies)."""

    id: uuid.UUID
    group_id: uuid.UUID | None
    title: str
    body: str
    tags: list[str]
    topic_id: uuid.UUID | None
    topic: str | None  # the topic's title
    unit_id: uuid.UUID | None
    is_question: bool
    author: AuthorOut | None  # None when the author deleted their account
    is_mine: bool
    # The author sees "pending" / "flagged" on their own post; others only see approved posts.
    moderation_status: ModerationStatus
    score: int
    reply_count: int
    accepted_reply_id: uuid.UUID | None
    created_at: datetime


class ReplyOut(BaseModel):
    id: uuid.UUID
    body: str
    author: AuthorOut | None  # None for an AI suggested answer or a deleted account
    is_mine: bool
    is_ai_suggested: bool
    is_accepted: bool
    moderation_status: ModerationStatus
    score: int
    created_at: datetime


class PostDetailOut(PostOut):
    """One post with its replies: the accepted answer first, then the highest score."""

    replies: list[ReplyOut]
