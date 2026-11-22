"""Request / response models (Pydantic) for the profiles module. Owner: Mogith.

Profile setup = 3 onboarding steps in the app:
  1. stream + subject   2. goal (exam year, target grade, confidence)   3. availability
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator

WEEK_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
PreferredTime = Literal["morning", "evening", "night"]
TargetGrade = Literal["A", "B", "C"]


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- GET /profile/options
class StreamOption(BaseModel):
    id: str
    name: str
    available: bool


class SubjectOption(BaseModel):
    id: str
    name: str
    units: int | None = None
    syllabus: str | None = None
    available: bool


class TimeOption(BaseModel):
    id: str
    label: str
    hint: str


class ProfileOptionsOut(BaseModel):
    streams: list[StreamOption]
    subjects: list[SubjectOption]
    exam_years: list[int]
    target_grades: list[str]
    preferred_times: list[TimeOption]


# ---------------------------------------------------------------- PATCH /profile
class ProfileUpdate(BaseModel):
    """Any subset of the fields. Send null to clear a field."""

    stream: str | None = Field(default=None, max_length=30)
    subject: str | None = Field(default=None, max_length=30)
    exam_year: int | None = None
    target_grade: TargetGrade | None = None
    confidence: int | None = Field(default=None, ge=0, le=100)
    study_days: list[Day] | None = None
    hours_per_day: float | None = None
    preferred_time: PreferredTime | None = None

    @field_validator("hours_per_day")
    @classmethod
    def half_hour_steps(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if not 0.5 <= value <= 6 or (value * 2) != int(value * 2):
            raise ValueError("must be between 0.5 and 6, in steps of 0.5")
        return value

    @field_validator("study_days")
    @classmethod
    def at_least_one_day(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if not value:
            raise ValueError("choose at least one day")
        return [d for d in WEEK_DAYS if d in value]  # remove duplicates, keep Mon..Sun order


# ---------------------------------------------------------------- ProfileOut
class ProfileOut(BaseModel):
    stream: str | None = None
    subject: str | None = None
    exam_year: int | None = None
    target_grade: str | None = None
    confidence: int | None = None
    study_days: list[str] | None = None
    hours_per_day: float | None = None
    preferred_time: str | None = None
    weekly_hours: float | None = None  # hours_per_day x number of study days
    profile_completed: bool = False


# ---------------------------------------------------------------- personal details
class PersonalDetailsOut(BaseModel):
    """The Edit profile page: who the student is (name and phone are saved by PATCH /auth/me)."""

    full_name: str
    email: str | None = None
    phone: str | None = None
    bio: str | None = None
    avatar_url: str | None = None  # a link the app can load without a login header


class PersonalDetailsUpdate(BaseModel):
    bio: str | None = Field(default=None, max_length=500)  # send null or "" to clear it


# ---------------------------------------------------------------- GET /profile/overview
class AchievementOut(BaseModel):
    id: str  # "streak_7"
    title: str
    icon: str  # streak | first_mastery | unit_fixer | mcq_100 | past_paper_pro | unit_master
    description: str
    unlocked: bool
    unlocked_at: datetime | None = None
    seen: bool  # false on an unlocked badge = the app shows the "Achievement unlocked" pop-up
    badge_label: str | None = None
    xp: int | None = None


class ProfileOverviewOut(BaseModel):
    """The Profile page (Figma F1) in one call."""

    full_name: str
    stream_label: str  # "Biological Science" ("" before profile setup)
    exam_year: int | None = None
    target_grade: str | None = None
    days_to_exam: int | None = None  # null if the year or its A/L date is unknown
    streak_days: int
    questions_answered: int
    topics_mastered: int
    # Unlocked ones first (newest first), then the locked ones in display order.
    achievements: list[AchievementOut]
    achievements_total: int


# ---------------------------------------------------------------- settings / privacy
HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


class _NoNulls(BaseModel):
    """PATCH bodies: send any subset of the fields, but never null."""

    @model_validator(mode="before")
    @classmethod
    def no_nulls(cls, data: Any) -> Any:
        if isinstance(data, dict):
            nulls = [k for k, v in data.items() if v is None and k in cls.model_fields]
            if nulls:
                raise ValueError(f"cannot be null: {', '.join(nulls)}")
        return data


class NotificationSettingsOut(BaseModel):
    study_reminders: bool
    reminder_time: str  # "HH:mm", 24 h, Sri Lanka time
    community_replies: bool


class NotificationSettingsUpdate(_NoNulls):
    study_reminders: StrictBool | None = None
    reminder_time: str | None = Field(
        default=None, pattern=HHMM, description='24 h "HH:mm", e.g. "20:30"'
    )
    community_replies: StrictBool | None = None


class PrivacySettingsOut(BaseModel):
    personalised_recommendations: bool = True  # always on (needed for the core app)
    improve_ai: bool
    show_name_in_community: bool
    share_research: bool


class PrivacySettingsUpdate(_NoNulls):
    personalised_recommendations: StrictBool | None = Field(
        default=None, description="Ignored: personalised recommendations are always on"
    )
    improve_ai: StrictBool | None = None
    show_name_in_community: StrictBool | None = None
    share_research: StrictBool | None = None
