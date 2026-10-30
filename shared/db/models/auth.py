"""6-digit email codes and password-reset tokens. Owner of the logic: Mogith (auth module).

Firebase Auth signs users in, but the app's designs use 6-digit codes (not Firebase's
email links), so the backend creates, emails and checks these codes itself.
Codes and tokens are NEVER stored in plain text - only an HMAC-SHA256 hash.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EmailCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One 6-digit code sent to an email address (verify email or reset password)."""

    __tablename__ = "email_codes"
    __table_args__ = (
        Index("ix_email_codes_email_purpose", "email", "purpose"),
        # "newest code for this email" lookups (the email is always stored lower-case)
        Index("ix_email_codes_email_purpose_created", "email", "purpose", "created_at"),
        CheckConstraint("purpose IN ('verify_email', 'reset_password')", name="purpose"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
    )

    # NULL for password-reset requests for unknown emails (we still store a row so the
    # response and the resend cooldown look the same - attackers can't tell who is registered).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))  # always lower-case
    purpose: Mapped[str] = mapped_column(String(20))  # "verify_email" | "reset_password"
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # wrong tries
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordResetToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Single-use token given after a correct reset code; lets the app set a new password."""

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
