"""Community: study groups, posts, replies, votes and reports.

Backend owner: Keshomigha. Mobile owner: Samni.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ModerationStatus


class CommunityGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A study group: one per unit plus a default "General" group."""

    __tablename__ = "community_groups"

    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str | None] = mapped_column(String(100), unique=True)  # e.g. "unit-6"
    description: Mapped[str | None] = mapped_column(Text)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"), index=True
    )
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    member_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class GroupMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A student in a group. `created_at` is the join time."""

    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_members_group_user"),
        CheckConstraint("role IN ('member', 'moderator', 'owner')", name="role"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_groups.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="member")  # member|moderator|owner


class Post(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A question / discussion post in a group. Kept (author = NULL) if the author leaves."""

    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_group_created", "group_id", "created_at"),
        Index("ix_posts_moderation_status", "moderation_status"),
        CheckConstraint("ai_tag_confidence BETWEEN 0 AND 1", name="ai_tag_confidence_range"),
    )

    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_groups.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)  # markdown (the spec's `body_md`)
    # Firebase Storage paths: posts/{post_id}/{n}.jpg
    image_paths: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    # The topic the AI thinks this post is about
    ai_tag_topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    ai_tag_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    is_question: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        str_enum(ModerationStatus), default=ModerationStatus.PENDING
    )
    moderation_reason: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # sum of votes
    reply_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Circular FK (posts <-> replies), so it is created after both tables (use_alter).
    accepted_reply_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "replies.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_posts_accepted_reply_id_replies",
        ),
        index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Reply(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An answer to a post (from a student, or suggested by the AI)."""

    __tablename__ = "replies"
    __table_args__ = (Index("ix_replies_post_created", "post_id", "created_at"),)

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    # NULL author = AI suggested answer (or the author deleted their account)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    body: Mapped[str] = mapped_column(Text)  # markdown (the spec's `body_md`)
    is_ai_suggested: Mapped[bool] = mapped_column(Boolean, default=False)  # the spec's is_ai_answer
    is_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    # RAG chunks an AI answer used: [{"chunk_id": "...", "page": 3}, ...]
    sources: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        str_enum(ModerationStatus), default=ModerationStatus.PENDING
    )
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_jobs.id", ondelete="SET NULL"), index=True
    )


class Vote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """+1 / -1 on a post OR a reply (exactly one of post_id / reply_id is set).

    The two unique constraints work like the spec's partial unique indexes, because
    Postgres treats NULLs as different values.
    """

    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uq_votes_user_post"),
        UniqueConstraint("user_id", "reply_id", name="uq_votes_user_reply"),
        CheckConstraint("value IN (-1, 1)", name="value_plus_minus_one"),
        CheckConstraint("num_nonnulls(post_id, reply_id) = 1", name="one_target"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    reply_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("replies.id", ondelete="CASCADE"), index=True
    )
    value: Mapped[int] = mapped_column(SmallInteger)  # +1 or -1


class ContentReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user reports a post or reply for moderation.

    `target_id` is polymorphic (a post id or a reply id, see `target_type`), so no FK.
    """

    __tablename__ = "content_reports"
    __table_args__ = (CheckConstraint("target_type IN ('post', 'reply')", name="target_type"),)

    reporter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(20))  # "post" | "reply"
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    reason: Mapped[str] = mapped_column(String(100))  # ContentReportReason value
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ModerationStatus] = mapped_column(
        str_enum(ModerationStatus), default=ModerationStatus.PENDING
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(  # the spec's `resolved_by`
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
