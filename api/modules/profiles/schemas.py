"""Request / response models (Pydantic) for the profiles module. Owner: Mogith.

Profile setup = 3 onboarding steps in the app:
  1. stream + subject   2. goal (exam year, target grade, confidence)   3. availability
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
