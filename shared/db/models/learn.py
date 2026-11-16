"""Learn tab tables that have no older equivalent. Owner: Samni.

Everything else the Learn tab needs is stored in existing tables (see api/modules/learn):
notes (official + a student's own), uploads + summaries, user_topic_progress, visuals
(diagrams), resources (videos) and ai_jobs (generation jobs).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, UUIDPrimaryKeyMixin


class TopicBookmark(UUIDPrimaryKeyMixin, Base):
    """A topic a student bookmarked. One row per (student, topic)."""

    __tablename__ = "topic_bookmarks"
    __table_args__ = (
        UniqueConstraint("user_id", "topic_id", name="uq_topic_bookmarks_user_topic"),
        Index("ix_topic_bookmarks_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
