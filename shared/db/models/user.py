"""Users and student profiles. Owner of the auth logic: Mogith. Schema owner: Keshomigha."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum
from shared.enums import UserRole


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per Firebase account (students and admins)."""

    __tablename__ = "users"

    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole), default=UserRole.STUDENT)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
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
