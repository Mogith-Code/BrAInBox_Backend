"""Request / response models (Pydantic) for the auth module. Owner: Mogith.

The Flutter app depends on these shapes exactly (see README.md). JSON is snake_case.
"""

import uuid

from pydantic import BaseModel, Field

from shared.enums import UserRole

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
CODE_PATTERN = r"^\d{6}$"


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- account
class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=30)  # e.g. "077 123 4567"
    consent: bool  # must be true: the student accepted the terms + privacy policy


class UpdateMeRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=30)  # send null to remove the phone


class OnboardingOut(BaseModel):
    profile_completed: bool
    diagnostic_completed: bool
    diagnostic_skipped: bool


class UserOut(BaseModel):
    id: uuid.UUID
    email: str | None
    full_name: str | None
    phone: str | None
    role: UserRole
    email_verified: bool
    onboarding: OnboardingOut


# ---------------------------------------------------------------- 6-digit codes
class CodeSentOut(BaseModel):
    sent: bool = True
    resend_in: int  # seconds until "Resend code" may be pressed
    expires_in: int  # seconds until the code expires
    dev_code: str | None = None  # ONLY in dev with DEV_EXPOSE_CODES=true


class VerifyCodeRequest(BaseModel):
    code: str = Field(pattern=CODE_PATTERN, description="The 6 digits from the email")


class PasswordResetSendRequest(BaseModel):
    email: str = Field(max_length=320, pattern=EMAIL_PATTERN)


class PasswordResetVerifyRequest(BaseModel):
    email: str = Field(max_length=320, pattern=EMAIL_PATTERN)
    code: str = Field(pattern=CODE_PATTERN)


class ResetTokenOut(BaseModel):
    reset_token: str
    expires_in: int


class PasswordResetCompleteRequest(BaseModel):
    reset_token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(max_length=128)


class ResetDoneOut(BaseModel):
    reset: bool = True
