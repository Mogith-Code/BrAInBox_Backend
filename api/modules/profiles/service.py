"""Business logic for the profiles module. Owner: Mogith.

Onboarding "profile setup" (3 steps) and the read helpers other modules use
(onboarding flags for auth, study settings for the home dashboard).

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service, never its repository.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.core.errors import AppError
from api.modules.profiles import repository
from api.modules.profiles.schemas import (
    ModuleStatus,
    ProfileOptionsOut,
    ProfileOut,
    ProfileUpdate,
    StreamOption,
    SubjectOption,
    TimeOption,
)
from shared.db.models import StudentProfile

MODULE_NAME = "profiles"

# What the app offers. Only Biology is available for now ("coming soon" for the others).
STREAMS = [StreamOption(id="bio_science", name="Biological Science", available=True)]
SUBJECTS = [
    SubjectOption(id="biology", name="Biology", units=10, syllabus="2025 syllabus", available=True),
    SubjectOption(id="chemistry", name="Chemistry", available=False),
    SubjectOption(id="physics", name="Physics", available=False),
]
TARGET_GRADES = ["A", "B", "C"]
PREFERRED_TIMES = [
    TimeOption(id="morning", label="Morning", hint="5–9 AM"),
    TimeOption(id="evening", label="Evening", hint="4–8 PM"),
    TimeOption(id="night", label="Night", hint="8 PM+"),
]
# Every field the app must fill before "Finish setup" (POST /profile/complete).
REQUIRED_FIELDS = [
    "stream",
    "subject",
    "exam_year",
    "target_grade",
    "confidence",
    "study_days",
    "hours_per_day",
    "preferred_time",
]


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


def exam_years() -> list[int]:
    """This year and the next two (2026 -> [2026, 2027, 2028]); moves on by itself each year."""
    year = clock.today().year
    return [year, year + 1, year + 2]


def get_options() -> ProfileOptionsOut:
    return ProfileOptionsOut(
        streams=STREAMS,
        subjects=SUBJECTS,
        exam_years=exam_years(),
        target_grades=TARGET_GRADES,
        preferred_times=PREFERRED_TIMES,
    )


def _to_out(profile: StudentProfile | None) -> ProfileOut:
    if profile is None:
        return ProfileOut()
    hours = float(profile.hours_per_day) if profile.hours_per_day is not None else None
    days = list(profile.study_days) if profile.study_days else None
    return ProfileOut(
        stream=profile.stream,
        subject=profile.subject,
        exam_year=profile.exam_year,
        target_grade=profile.target_grade,
        confidence=profile.confidence,
        study_days=days,
        hours_per_day=hours,
        preferred_time=profile.preferred_time,
        weekly_hours=round(hours * len(days), 1) if hours is not None and days else None,
        profile_completed=profile.profile_completed_at is not None,
    )


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> ProfileOut:
    """An empty profile (all null) until the student saves something."""
    return _to_out(await repository.get_by_user_id(session, user_id))


def _check_available(req: ProfileUpdate) -> None:
    fields = req.model_fields_set
    if "stream" in fields and req.stream is not None:
        if not any(s.id == req.stream and s.available for s in STREAMS):
            raise AppError("This stream is not available yet", code="STREAM_NOT_AVAILABLE")
    if "subject" in fields and req.subject is not None:
        if not any(s.id == req.subject and s.available for s in SUBJECTS):
            raise AppError("This subject is coming soon", code="SUBJECT_NOT_AVAILABLE")
    if "exam_year" in fields and req.exam_year is not None and req.exam_year not in exam_years():
        raise AppError(f"Choose an exam year from {exam_years()}", code="INVALID_EXAM_YEAR")


async def update_profile(
    session: AsyncSession, user_id: uuid.UUID, req: ProfileUpdate
) -> ProfileOut:
    """Save any subset of the setup fields (creates the profile on the first call)."""
    _check_available(req)
    profile = await repository.get_by_user_id(session, user_id)
    if profile is None:
        profile = StudentProfile(user_id=user_id)
        session.add(profile)
    for field in req.model_fields_set:
        value = getattr(req, field)
        if field == "hours_per_day" and value is not None:
            value = Decimal(str(value))
        setattr(profile, field, value)
    await session.commit()
    return _to_out(profile)


async def complete_profile(session: AsyncSession, user_id: uuid.UUID) -> ProfileOut:
    """ "Finish setup": every required field must be filled."""
    profile = await repository.get_by_user_id(session, user_id)
    missing = [f for f in REQUIRED_FIELDS if profile is None or getattr(profile, f) in (None, [])]
    if profile is None or missing:
        raise AppError(
            "Please fill in: " + ", ".join(missing),
            code="PROFILE_INCOMPLETE",
            extra={"missing": missing},
        )
    if profile.profile_completed_at is None:
        profile.profile_completed_at = clock.now()
        await session.commit()
    return _to_out(profile)


# =========================================================================== for other modules


async def get_onboarding_flags(session: AsyncSession, user_id: uuid.UUID) -> tuple[bool, bool]:
    """(profile_completed, diagnostic_skipped) for the auth module's UserOut."""
    profile = await repository.get_by_user_id(session, user_id)
    if profile is None:
        return False, False
    return profile.profile_completed_at is not None, profile.diagnostic_skipped_at is not None


async def mark_diagnostic_skipped(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Used by the quizzes module when the student taps "Skip for now"."""
    profile = await repository.get_by_user_id(session, user_id)
    if profile is None:
        profile = StudentProfile(user_id=user_id)
        session.add(profile)
    if profile.diagnostic_skipped_at is None:
        profile.diagnostic_skipped_at = clock.now()
    await session.commit()


@dataclass
class StudySettings:
    """What the home dashboard needs from the profile."""

    exam_year: int | None
    study_days: list[str]
    hours_per_day: float | None
    diagnostic_skipped: bool


async def get_study_settings(session: AsyncSession, user_id: uuid.UUID) -> StudySettings:
    profile = await repository.get_by_user_id(session, user_id)
    if profile is None:
        return StudySettings(None, [], None, False)
    return StudySettings(
        exam_year=profile.exam_year,
        study_days=list(profile.study_days or []),
        hours_per_day=float(profile.hours_per_day) if profile.hours_per_day is not None else None,
        diagnostic_skipped=profile.diagnostic_skipped_at is not None,
    )
