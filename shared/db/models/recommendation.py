"""Learning resources, recommendations and study plans. Owner: Udith."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import (
    ContentStatus,
    PlanSource,
    RecommendationAction,
    RecommendationStatus,
    StudyPlanStatus,
)


class Resource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An external or internal resource (YouTube video, article, note). Owner: Udith."""

    __tablename__ = "resources"
    __table_args__ = (
        # The same YouTube video (etc.) is stored only once.
        Index(
            "uq_resources_provider_external_id",
            "provider",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        CheckConstraint("quality_score BETWEEN 0 AND 1", name="quality_score_range"),
    )

    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000))
    # "youtube" | "article" | "note" (older values) or a ResourceKind value (the spec's `kind`)
    resource_type: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str | None] = mapped_column(String(50))  # ResourceProvider value
    external_id: Mapped[str | None] = mapped_column(String(100), index=True)  # e.g. video id
    channel: Mapped[str | None] = mapped_column(String(200))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en", server_default="en")
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    """A next step suggested to one student ("Watch this video on osmosis"). Owner: Udith."""

    __tablename__ = "recommendations"
    __table_args__ = (
        Index("ix_recommendations_user_status_priority", "user_id", "status", "priority"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="priority_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    action_type: Mapped[RecommendationAction | None] = mapped_column(str_enum(RecommendationAction))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resources.id", ondelete="SET NULL"), index=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    # What to open, e.g. {"note_id": "..."} or quiz settings {"topic_id": "...", "count": 10}
    target_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    reason: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    priority: Mapped[int] = mapped_column(SmallInteger, default=3, server_default="3")  # 1 = top
    status: Mapped[RecommendationStatus] = mapped_column(
        str_enum(RecommendationStatus),
        default=RecommendationStatus.PENDING,
        server_default="pending",
    )
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)  # older flag
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudyPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A multi-day study plan for one student (only one active at a time). Owner: Udith."""

    __tablename__ = "study_plans"
    __table_args__ = (
        Index(
            "uq_study_plans_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint("end_date >= start_date", name="dates_in_order"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[StudyPlanStatus] = mapped_column(
        str_enum(StudyPlanStatus), default=StudyPlanStatus.ACTIVE, server_default="active"
    )
    generated_from: Mapped[PlanSource] = mapped_column(
        str_enum(PlanSource), default=PlanSource.MANUAL, server_default="manual"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # older flag; use `status`


class PlanItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One task of a study plan on one day. Owner: Udith."""

    __tablename__ = "plan_items"

    study_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("study_plans.id", ondelete="CASCADE"), index=True
    )
    action_type: Mapped[RecommendationAction | None] = mapped_column(str_enum(RecommendationAction))
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL"), index=True
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resources.id", ondelete="SET NULL"), index=True
    )
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[date | None] = mapped_column(Date)  # the spec's `scheduled_date`
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    order_index: Mapped[int] = mapped_column(Integer, default=0)


class DailyPlanItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One task in a student's plan for one day ("Today's plan" on the home screen).

    Created on the first home request of the day, so done/undone is remembered. Owner: Mogith.
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
    position: Mapped[int] = mapped_column(Integer)  # 1, 2, 3 (the spec's `order_index`)
    kind: Mapped[str] = mapped_column(String(20))  # "recap" | "practice" | "read"
    title: Mapped[str] = mapped_column(String(200))
    minutes: Mapped[int] = mapped_column(Integer)  # the spec's `estimated_minutes`
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("units.id", ondelete="SET NULL"), index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True
    )
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
