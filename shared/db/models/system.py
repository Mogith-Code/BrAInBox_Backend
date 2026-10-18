"""System tables: AI jobs, AI usage/cost log and the admin audit log. Shared by everyone."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import JobStatus, JobType


class AIJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A long-running AI task. The app polls GET /api/v1/jobs/{id} for its status."""

    __tablename__ = "ai_jobs"

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

    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_jobs.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50))  # "gemini", "vision", ...
    model: Mapped[str | None] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(50))  # "generate", "embed", "ocr", ...
    prompt_name: Mapped[str | None] = mapped_column(String(100))  # e.g. "notes/generate_notes.v1"
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))
    success: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Who did what in the admin portal."""

    __tablename__ = "audit_log"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100))  # e.g. "question.approve"
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    ip_address: Mapped[str | None] = mapped_column(String(45))
