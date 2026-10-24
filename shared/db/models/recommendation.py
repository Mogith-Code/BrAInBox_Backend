"""Learning resources, recommendations and study plans. Owner: Udith."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


class DailyPlanItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One task in a student's plan for one day ("Today's plan" on the home screen).

    Created on the first home request of the day, so done/undone is remembered.
    """

    __tablename__ = "daily_plan_items"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "plan_date", "position", name="uq_daily_plan_items_user_date_position"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    plan_date: Mapped[date] = mapped_column(Date)  # the student's local date
    position: Mapped[int] = mapped_column(Integer)  # 1, 2, 3
    kind: Mapped[str] = mapped_column(String(20))  # "recap" | "practice" | "read"
    title: Mapped[str] = mapped_column(String(200))
    minutes: Mapped[int] = mapped_column(Integer)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
