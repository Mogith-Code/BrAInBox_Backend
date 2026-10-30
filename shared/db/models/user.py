"""Users and student profiles. Owner of the auth logic: Mogith. Schema owner: Keshomigha."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import UserRole


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per Firebase account (students and admins)."""

    __tablename__ = "users"

    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120))  # the API calls it "full_name"
    phone: Mapped[str | None] = mapped_column(String(20))  # E.164, e.g. +94771234567
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole), default=UserRole.STUDENT)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Set by our 6-digit email code, or copied from the Firebase token (e.g. Google sign-in).
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # terms accepted
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudentProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Extra details for a student (one profile per user)."""

    __tablename__ = "student_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    school: Mapped[str | None] = mapped_column(String(200))
    district: Mapped[str | None] = mapped_column(String(100))
    exam_year: Mapped[int | None] = mapped_column(Integer)  # A/L exam year, e.g. 2027
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    bio: Mapped[str | None] = mapped_column(String(500))

    # --- onboarding "profile setup" (3 steps in the app)
    stream: Mapped[str | None] = mapped_column(String(30))  # e.g. "bio_science"
    subject: Mapped[str | None] = mapped_column(String(30))  # e.g. "biology"
    target_grade: Mapped[str | None] = mapped_column(String(1))  # "A" | "B" | "C"
    confidence: Mapped[int | None] = mapped_column(Integer)  # 0-100 slider
    study_days: Mapped[list[str] | None] = mapped_column(ARRAY(String(3)))  # ["mon", "tue", ...]
    hours_per_day: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))  # 0.5 - 6.0
    preferred_time: Mapped[str | None] = mapped_column(String(10))  # morning | evening | night
    profile_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diagnostic_skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
