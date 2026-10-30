"""Users, student profiles, settings, push-device tokens and in-app notifications.

Owner of the auth logic: Mogith. Schema owner: Keshomigha.
"""

import uuid
from datetime import datetime, time
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
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import DevicePlatform, NotificationType, ThemeMode, UserRole


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per Firebase account (students and admins). Owner: Mogith (auth)."""

    __tablename__ = "users"
    __table_args__ = (
        # Emails are compared case-insensitively ("Nethmi@x.com" == "nethmi@x.com").
        Index(
            "uq_users_email_lower",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        # E.164 phone number, e.g. +94771234567
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name="phone_e164"),
    )

    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    # The API (and the spec) call it "full_name"; the column keeps its first name.
    display_name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))  # E.164, e.g. +94771234567
    avatar_url: Mapped[str | None] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(
        str_enum(UserRole), default=UserRole.STUDENT, server_default="student", index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by our 6-digit email code, or copied from the Firebase token (e.g. Google sign-in).
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # terms accepted
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudentProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Extra details for a student (one profile per user). Owner: Mogith (profiles)."""

    __tablename__ = "student_profiles"
    __table_args__ = (
        CheckConstraint("exam_year BETWEEN 2025 AND 2035", name="exam_year_range"),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="confidence_range"),
        CheckConstraint("hours_per_day > 0 AND hours_per_day <= 12", name="hours_per_day_range"),
        CheckConstraint("target_grade IN ('A', 'B', 'C', 'S')", name="target_grade"),
        CheckConstraint(
            "preferred_time IN ('morning', 'afternoon', 'evening', 'night')",
            name="preferred_time",
        ),
        CheckConstraint("stream IN ('bio_science')", name="stream"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    school: Mapped[str | None] = mapped_column(String(200))
    district: Mapped[str | None] = mapped_column(String(100))
    exam_year: Mapped[int | None] = mapped_column(Integer)  # A/L exam year, e.g. 2027
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    bio: Mapped[str | None] = mapped_column(String(500))

    # --- onboarding "profile setup" (3 steps in the app)
    stream: Mapped[str | None] = mapped_column(String(30))  # "bio_science"
    subject: Mapped[str | None] = mapped_column(String(30))  # "biology"
    target_grade: Mapped[str | None] = mapped_column(String(1))  # "A" | "B" | "C" | "S"
    confidence: Mapped[int | None] = mapped_column(Integer)  # 0-100 slider
    study_days: Mapped[list[str] | None] = mapped_column(ARRAY(String(3)))  # ["mon", "tue", ...]
    hours_per_day: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))  # 0.5 - 6.0
    preferred_time: Mapped[str | None] = mapped_column(String(10))  # morning | evening | night
    profile_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diagnostic_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diagnostic_skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSettings(TimestampMixin, Base):
    """App settings of one user (theme, reminders). Owner: Mogith (profiles)."""

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[ThemeMode] = mapped_column(
        str_enum(ThemeMode), default=ThemeMode.SYSTEM, server_default="system"
    )
    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    daily_reminder_time: Mapped[time | None] = mapped_column(Time)  # local time, e.g. 19:30
    email_updates: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class DeviceToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A phone / browser that can receive push notifications (FCM). Owner: Mogith."""

    __tablename__ = "device_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    fcm_token: Mapped[str] = mapped_column(Text, unique=True)
    platform: Mapped[DevicePlatform] = mapped_column(str_enum(DevicePlatform))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An in-app notification ("Your study plan is ready"). Owner: Mogith."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
        # Fast "unread count" badge.
        Index("ix_notifications_unread", "user_id", postgresql_where=text("read_at IS NULL")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[NotificationType] = mapped_column(str_enum(NotificationType))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    # Where a tap goes, e.g. {"screen": "plan", "plan_id": "..."}
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
