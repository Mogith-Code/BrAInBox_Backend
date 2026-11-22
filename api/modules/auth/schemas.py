"""Request / response models (Pydantic) for the auth module. Owner: Mogith.

The Flutter app depends on these shapes exactly (see README.md). JSON is snake_case.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

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


# ---------------------------------------------------------------- my data export
class CommunityExportOut(BaseModel):
    posts: list[dict[str, Any]]
    replies: list[dict[str, Any]]


class DataExportOut(BaseModel):
    """GET /auth/me/export: everything we store about the caller. The app saves it as .json.

    Files (answer photos, uploads, post images) are Storage paths, not the files.
    """

    exported_at: str  # ISO 8601, UTC
    account: dict[str, Any]
    profile: dict[str, Any] | None  # null before profile setup
    settings: dict[str, Any]
    privacy: dict[str, Any]  # Data & privacy switches + terms accepted + push device count
    achievements: list[dict[str, Any]]  # only the unlocked ones
    quiz_attempts: list[dict[str, Any]]  # quizzes, practice and the diagnostic
    exam_attempts: list[dict[str, Any]]
    evaluations: list[dict[str, Any]]
    mistakes: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    study_plan: dict[str, Any]  # {"plans": [... with items], "daily_items": [...]}
    notes: list[dict[str, Any]]
    uploads: list[dict[str, Any]]
    bookmarks: list[dict[str, Any]]  # topic bookmarks (Learn tab)
    community: CommunityExportOut
    notifications: list[dict[str, Any]]


# ---------------------------------------------------------------- admin: Students (users_admin.py)
StudentStatus = Literal["active", "suspended", "inactive"]


class AdminStudentOut(BaseModel):
    """One row of the admin Students table (BrAInBox_Mobile apps/admin users_models.dart)."""

    id: uuid.UUID
    full_name: str
    email: str | None = None
    school: str | None = None
    district: str | None = None
    exam_year: int | None = None
    avg_mastery: int | None = None  # 0-100, null = no mastery data yet
    status: StudentStatus
    last_active_at: datetime | None = None


class AdminStudentPage(BaseModel):
    items: list[AdminStudentOut]
    total: int
    active_total: int


class AdminStudentUpdate(BaseModel):
    is_active: bool
