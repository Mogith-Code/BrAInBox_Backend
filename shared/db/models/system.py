"""System tables: AI jobs, AI usage/cost log, the admin audit log and app settings.

Shared by everyone.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import JobStatus, JobType


class AIJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A long-running AI task. The app polls GET /api/v1/jobs/{id} for its status."""

    __tablename__ = "ai_jobs"
    __table_args__ = (
        Index("ix_ai_jobs_status_created", "status", "created_at"),  # the worker's queue
        Index("ix_ai_jobs_requested_by_created", "requested_by", "created_at"),
    )

    job_type: Mapped[JobType] = mapped_column(str_enum(JobType), index=True)
    status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus), default=JobStatus.QUEUED, index=True
    )
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIUsageLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per call to an AI provider (tokens, latency, cost)."""

    __tablename__ = "ai_usage_log"
    __table_args__ = (
        Index("ix_ai_usage_log_created", "created_at"),
        Index("ix_ai_usage_log_operation_created", "operation", "created_at"),
        Index("ix_ai_usage_log_user_created", "user_id", "created_at"),
    )

    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_jobs.id", ondelete="SET NULL"), index=True
    )
    # Who caused the cost (for per-student daily limits)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50))  # "gemini", "vision", ...
    model: Mapped[str | None] = mapped_column(String(100))
    # The spec's `feature`: "generate", "embed", "ocr", ...
    operation: Mapped[str] = mapped_column(String(50))
    prompt_name: Mapped[str | None] = mapped_column(String(100))  # e.g. "notes/generate_notes.v1"
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    images: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # images generated
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    success: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Who did what in the admin portal."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_target", "target_type", "target_id"),
        Index("ix_audit_log_actor_created", "actor_id", "created_at"),
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100))  # e.g. "question.approve"
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # The row before / after the change (only the fields that matter)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(45))


class AppConfig(Base):
    """App-wide settings an admin can change without a deploy, e.g. AL_EXAM_DATES.

    One row per key; `value` is any JSON.
    """

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "DAILY_LIMITS"
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
