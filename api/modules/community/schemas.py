"""Request / response models (Pydantic) for the community module. Owner: Mogith.

Student models: groups, posts, replies, votes, reports (StudyGroupOut, PostOut, ...).
The admin models match the Flutter admin app
(BrAInBox_Mobile apps/admin/lib/features/moderation/domain/moderation_models.dart).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from shared.enums import ContentReportReason, ModerationStatus

MAX_TAGS = 5


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- groups
class StudyGroupOut(BaseModel):
    """A study group, as the logged-in student sees it. (GroupOut below is the admin view.)"""

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
    my_vote: int  # my vote on it: 1, -1 or 0 (none)
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
    my_vote: int  # my vote on it: 1, -1 or 0 (none)
    created_at: datetime


class PostDetailOut(PostOut):
    """One post with its replies: the accepted answer first, then the highest score."""

    replies: list[ReplyOut]


# ---------------------------------------------------------------- replies
class ReplyCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5_000)  # markdown


class ReplyUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=5_000)


# ---------------------------------------------------------------- votes
class VoteIn(BaseModel):
    """Vote on exactly one post or one reply. value 0 removes my vote."""

    post_id: uuid.UUID | None = None
    reply_id: uuid.UUID | None = None
    value: Literal[1, -1, 0]

    @model_validator(mode="after")
    def one_target(self) -> "VoteIn":
        if (self.post_id is None) == (self.reply_id is None):
            raise ValueError("send exactly one of post_id or reply_id")
        return self


class VoteOut(BaseModel):
    target_type: Literal["post", "reply"]
    target_id: uuid.UUID
    my_vote: int  # 1, -1 or 0
    score: int  # the new total


# ---------------------------------------------------------------- reports
class ReportIn(BaseModel):
    reason: ContentReportReason
    details: str | None = Field(default=None, max_length=1_000)


class ReportOut(BaseModel):
    id: uuid.UUID
    target_type: Literal["post", "reply"]
    target_id: uuid.UUID
    reason: ContentReportReason
    status: ModerationStatus  # pending until an admin looks at it
    created_at: datetime


# ---------------------------------------------------------------- admin: moderation queue
ReportTargetType = Literal["post", "reply", "visual"]
ModerationAction = Literal["keep", "warn", "remove"]


class ModerationItemOut(BaseModel):
    """One reported post / reply / visual. All open reports of the same target are one item;
    `id` is the oldest open report (use it to resolve them all)."""

    id: uuid.UUID
    target_type: ReportTargetType
    target_id: uuid.UUID
    reason: str
    details: str | None = None
    author_handle: str | None = None
    group_name: str | None = None
    text: str | None = None  # post / reply text (or the visual's prompt)
    visual_title: str | None = None
    image_url: str | None = None
    ai_flag_label: str | None = None
    ai_flag_score: float | None = None  # 0-1
    report_count: int = 1
    created_at: datetime


class ResolveReportIn(BaseModel):
    action: ModerationAction


# ---------------------------------------------------------------- admin: study groups
class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    members: int
    moderator_name: str | None = None  # null = no moderator yet
    is_open: bool


class GroupCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Name must have at least 2 characters")
        return value


class TopicSuggestIn(BaseModel):
    """The draft of a post, to suggest its topic tag before posting."""

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=10_000)
    group_id: str | None = None  # a unit group limits the choice to that unit's topics


class TopicSuggestOut(BaseModel):
    topic_id: uuid.UUID | None  # null = no topic fits (the student can still pick one)
    topic: str | None
    unit_number: int | None
    confidence: float
    ai_generated: bool = True
