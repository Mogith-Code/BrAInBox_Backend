"""Learning resources, recommendations and study plans. Owner: Udith."""

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import ContentStatus


class Resource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An external or internal resource (YouTube video, article, note)."""

    __tablename__ = "resources"

    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000))
    resource_type: Mapped[str] = mapped_column(String(20))  # "youtube" | "article" | "note"
    provider: Mapped[str | None] = mapped_column(String(50))
    external_id: Mapped[str | None] = mapped_column(String(100), index=True)  # e.g. video id
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[ContentStatus] = mapped_column(
        str_enum(ContentStatus), default=ContentStatus.PENDING_REVIEW
    )


class Recommendation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recommendations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), index=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), index=True
    )
    reason: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)


class StudyPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "study_plans"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PlanItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plan_items"

    study_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("study_plans.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resources.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[date | None] = mapped_column(Date)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
