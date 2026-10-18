"""Community: study groups, posts, replies, votes and reports. Owner: Mogith."""

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ModerationStatus


class CommunityGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_groups"

    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"), index=True
    )
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class GroupMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_members_group_user"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_groups.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="member")  # member|moderator|owner


class Post(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "posts"

    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_groups.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        str_enum(ModerationStatus), default=ModerationStatus.PENDING
    )


class Reply(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "replies"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    # NULL author = AI suggested answer
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
    is_ai_suggested: Mapped[bool] = mapped_column(Boolean, default=False)
    is_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        str_enum(ModerationStatus), default=ModerationStatus.PENDING
    )


class Vote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """+1 / -1 on a post OR a reply (exactly one of post_id / reply_id is set)."""

    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uq_votes_user_post"),
        UniqueConstraint("user_id", "reply_id", name="uq_votes_user_reply"),
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
    """A user reports a post or reply for moderation."""

    __tablename__ = "content_reports"

    reporter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[str] = mapped_column(String(20))  # "post" | "reply"
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    reason: Mapped[str] = mapped_column(String(100))
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ModerationStatus] = mapped_column(
        str_enum(ModerationStatus), default=ModerationStatus.PENDING
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
