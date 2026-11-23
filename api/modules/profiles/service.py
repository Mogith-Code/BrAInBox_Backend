"""Business logic for the profiles module. Owner: Mogith.

Onboarding "profile setup" (3 steps) and the read helpers other modules use
(onboarding flags for auth, study settings for the home dashboard).
Also the Profile page (GET /profile/overview), achievements, and the Settings > Notifications
and Data & privacy switches (one `user_settings` row per student, created on the first PATCH).

Achievements are awarded when their event happens: the modules that own the event (quizzes,
exams, evaluation, learn, home, recommendations) call `check_achievements(...)` before their
commit. The facts come from the performance service, so no other module's tables are read here.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service, never its repository.
"""

import uuid
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from typing import Any

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock, storage
from api.core.config import get_settings
from api.core.errors import AppError, NotFoundError
from api.core.security import CurrentUser
from api.modules.performance import service as performance_service
from api.modules.profiles import repository
from api.modules.profiles.schemas import (
    AchievementOut,
    ModuleStatus,
    NotificationSettingsOut,
    NotificationSettingsUpdate,
    PersonalDetailsOut,
    PersonalDetailsUpdate,
    PrivacySettingsOut,
    PrivacySettingsUpdate,
    ProfileOptionsOut,
    ProfileOut,
    ProfileOverviewOut,
    ProfileUpdate,
    StreamOption,
    SubjectOption,
    TimeOption,
)
from shared.db.models import Achievement, StudentProfile, UserAchievement, UserSettings

MODULE_NAME = "profiles"
# Inside "visuals/" because the dev file route only serves that folder.
AVATAR_FOLDER = "visuals/avatars"
MAX_AVATAR_BYTES = 3 * 1024 * 1024

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


async def main_batch_year(session: AsyncSession) -> int:
    """The A/L year most students are preparing for (next year if nobody chose one yet)."""
    year = clock.today().year
    return await repository.most_common_exam_year(session, year) or year + 1


# =========================================================================== account delete / export
# Called by the auth module (DELETE /auth/me and GET /auth/me/export).


async def export_user_data(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """{"profile": {...} | None, "settings": {...}, "privacy": {...}, "achievements": [...]}.
    Settings / privacy show the defaults when the student never changed them; achievements
    are only the ones the student unlocked."""
    p = await repository.get_by_user_id(session, user_id)
    profile = None
    if p is not None:
        profile = {
            "school": p.school,
            "district": p.district,
            "exam_year": p.exam_year,
            "avatar_url": p.avatar_url,
            "bio": p.bio,
            "stream": p.stream,
            "subject": p.subject,
            "target_grade": p.target_grade,
            "confidence": p.confidence,
            "study_days": list(p.study_days) if p.study_days else None,
            "hours_per_day": float(p.hours_per_day) if p.hours_per_day is not None else None,
            "preferred_time": p.preferred_time,
            "profile_completed_at": p.profile_completed_at,
            "diagnostic_completed_at": p.diagnostic_completed_at,
            "diagnostic_skipped_at": p.diagnostic_skipped_at,
        }
    s = await repository.get_settings_row(session, user_id)
    settings = {
        "theme": s.theme if s else "system",
        "notifications_enabled": s.notifications_enabled if s else True,
        "daily_reminder_time": s.daily_reminder_time if s else None,
        "email_updates": s.email_updates if s else False,
        **_notification_out(s).model_dump(),
    }
    titles = {a.id: a.title for a in await repository.list_achievements(session)}
    unlocks = sorted(
        (await repository.user_achievements(session, user_id)).values(),
        key=lambda u: u.unlocked_at,
    )
    achievements = [
        {
            "id": u.achievement_id,
            "title": titles.get(u.achievement_id, u.achievement_id),
            "detail": u.detail,
            "unlocked_at": u.unlocked_at,
            "seen_at": u.seen_at,
        }
        for u in unlocks
    ]
    return {
        "profile": profile,
        "settings": settings,
        "privacy": _privacy_out(s).model_dump(),
        "achievements": achievements,
    }


async def delete_user_data(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """Delete the student's profile, settings and achievements (no commit).
    Returns the student's profile photo folder, so the auth module deletes it too."""
    await repository.delete_user_rows(session, user_id)
    return [f"{AVATAR_FOLDER}/{user_id}/"]


# =========================================================================== personal details
# Edit profile: bio and photo. Name and phone are saved by PATCH /auth/me.


def _image_extension(data: bytes) -> str | None:
    """Look at the file's first bytes, because a file name or content type can be faked."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


async def _details_out(
    session: AsyncSession, user: CurrentUser, base_url: str
) -> PersonalDetailsOut:
    profile = await repository.get_by_user_id(session, user.id)
    saved = profile.avatar_url if profile else None
    # An older value can be a full link (a Google photo); ours are Storage paths.
    avatar = saved if saved and saved.startswith("http") else None
    if saved and avatar is None:
        avatar = await storage.public_image_url(saved, base_url)
    return PersonalDetailsOut(
        full_name=(user.full_name or "").strip(),
        email=user.email,
        phone=await repository.get_phone(session, user.id),
        bio=profile.bio if profile else None,
        avatar_url=avatar,
    )


async def get_details(
    session: AsyncSession, user: CurrentUser, base_url: str
) -> PersonalDetailsOut:
    return await _details_out(session, user, base_url)


async def _get_or_create_profile(session: AsyncSession, user_id: uuid.UUID) -> StudentProfile:
    profile = await repository.get_by_user_id(session, user_id)
    if profile is None:
        profile = StudentProfile(user_id=user_id)
        session.add(profile)
    return profile


async def update_details(
    session: AsyncSession, user: CurrentUser, req: PersonalDetailsUpdate, base_url: str
) -> PersonalDetailsOut:
    profile = await _get_or_create_profile(session, user.id)
    if "bio" in req.model_fields_set:
        profile.bio = (req.bio or "").strip() or None
    await session.commit()
    return await _details_out(session, user, base_url)


async def save_avatar(
    session: AsyncSession, user: CurrentUser, data: bytes, base_url: str
) -> PersonalDetailsOut:
    """Store a new photo (JPEG, PNG or WebP, up to 3 MB), then remove the old one."""
    if len(data) > MAX_AVATAR_BYTES:
        raise AppError("The photo must be 3 MB or smaller", code="AVATAR_TOO_LARGE")
    extension = _image_extension(data)
    if extension is None:
        raise AppError("Choose a JPEG, PNG or WebP photo", code="AVATAR_INVALID")

    path = f"{AVATAR_FOLDER}/{user.id}/{uuid.uuid4().hex}.{extension}"
    content_type = "image/jpeg" if extension == "jpg" else f"image/{extension}"
    await run_in_threadpool(storage.upload_bytes, path, data, content_type)

    profile = await _get_or_create_profile(session, user.id)
    old = profile.avatar_url
    profile.avatar_url = path
    await session.commit()
    if old and old.startswith(f"{AVATAR_FOLDER}/{user.id}/"):
        await run_in_threadpool(storage.delete_files, [old])
    return await _details_out(session, user, base_url)


async def remove_avatar(
    session: AsyncSession, user: CurrentUser, base_url: str
) -> PersonalDetailsOut:
    profile = await repository.get_by_user_id(session, user.id)
    old = profile.avatar_url if profile else None
    if profile is not None:
        profile.avatar_url = None
        await session.commit()
    if old and old.startswith(f"{AVATAR_FOLDER}/{user.id}/"):
        await run_in_threadpool(storage.delete_files, [old])
    return await _details_out(session, user, base_url)


# =========================================================================== GET /profile/overview


def days_to_exam(exam_year: int | None) -> int | None:
    """Days from today (Sri Lanka) to the A/L exam; null if the year or its date is unknown.
    The dates are the AL_EXAM_DATES setting."""
    if exam_year is None:
        return None
    exam_date = get_settings().AL_EXAM_DATES.get(exam_year)
    if exam_date is None:
        return None
    return max(0, (exam_date - clock.today()).days)


def stream_label(stream: str | None) -> str:
    return next((s.name for s in STREAMS if s.id == stream), "")


def achievement_out(a: Achievement, unlock: UserAchievement | None) -> AchievementOut:
    return AchievementOut(
        id=a.id,
        title=a.title,
        icon=a.icon,
        description=unlock.detail if unlock and unlock.detail else a.description,
        unlocked=unlock is not None,
        unlocked_at=unlock.unlocked_at if unlock else None,
        seen=unlock is not None and unlock.seen_at is not None,
        badge_label=a.badge_label,
        xp=a.xp,
    )


async def list_achievements(session: AsyncSession, user_id: uuid.UUID) -> list[AchievementOut]:
    """Every achievement: unlocked ones first (newest first), then the locked ones."""
    definitions = await repository.list_achievements(session)
    unlocks = await repository.user_achievements(session, user_id)
    unlocked = sorted(
        (a for a in definitions if a.id in unlocks),
        key=lambda a: unlocks[a.id].unlocked_at,
        reverse=True,
    )
    locked = [a for a in definitions if a.id not in unlocks]
    return [achievement_out(a, unlocks.get(a.id)) for a in [*unlocked, *locked]]


async def get_overview(session: AsyncSession, user: CurrentUser) -> ProfileOverviewOut:
    """GET /profile/overview: the Profile page, from real data only."""
    profile = await repository.get_by_user_id(session, user.id)
    exam_year = profile.exam_year if profile else None
    achievements = await list_achievements(session, user.id)
    return ProfileOverviewOut(
        full_name=(user.full_name or "").strip(),
        stream_label=stream_label(profile.stream if profile else None),
        exam_year=exam_year,
        target_grade=profile.target_grade if profile else None,
        days_to_exam=days_to_exam(exam_year),
        streak_days=await performance_service.get_streak(session, user.id),
        questions_answered=await performance_service.count_answers(session, user.id),
        topics_mastered=await performance_service.count_mastered_topics(session, user.id),
        achievements=achievements,
        achievements_total=len(achievements),
    )


# =========================================================================== achievements
# Each rule returns None (not earned yet) or the personal text to store ("" = use the general
# description). The ids are the rows seeded by migration 0011.

STREAK_DAYS = 7
MCQ_GOAL = 100

Rule = Callable[[AsyncSession, uuid.UUID], Awaitable[str | None]]


async def _streak(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    if await performance_service.get_streak(session, user_id) >= STREAK_DAYS:
        return f"You studied {STREAK_DAYS} days in a row."
    return None


async def _first_mastery(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    return "" if await performance_service.count_mastered_topics(session, user_id) else None


async def _unit_fixer(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    units = await performance_service.units_weak_to_strong(session, user_id)
    return f"You took {units[0]} from Weak to Strong." if units else None


async def _mcq_100(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    answered = await performance_service.count_answers(session, user_id, mcq_only=True)
    return "" if answered >= MCQ_GOAL else None


async def _past_paper(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    return "" if await performance_service.has_submitted_past_paper(session, user_id) else None


async def _unit_master(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    units = await performance_service.fully_mastered_units(session, user_id)
    return f"You mastered every topic in {units[0]}." if units else None


ACHIEVEMENT_RULES: dict[str, Rule] = {
    "streak_7": _streak,
    "first_mastery": _first_mastery,
    "unit_fixer": _unit_fixer,
    "mcq_100": _mcq_100,
    "past_paper_pro": _past_paper,
    "unit_master": _unit_master,
}
# What a single answer / study action can unlock (cheap checks). Submitting a paper, quiz or
# the diagnostic, or mastering a topic, checks everything (only=None).
ACTIVITY_ACHIEVEMENTS = ("streak_7", "mcq_100")


async def check_achievements(
    session: AsyncSession, user_id: uuid.UUID, only: Collection[str] | None = None
) -> list[str]:
    """Unlock every achievement the student has now earned (all, or just `only`). Call it after
    the event, before your commit (no commit here). Returns the ids unlocked by this call.

        await profiles_service.check_achievements(session, user.id)
    """
    await session.flush()  # the caller's new answers / progress must be included
    unlocks = await repository.user_achievements(session, user_id)
    added: list[str] = []
    for a in await repository.list_achievements(session):
        rule = ACHIEVEMENT_RULES.get(a.id)
        if rule is None or a.id in unlocks or (only is not None and a.id not in only):
            continue
        detail = await rule(session, user_id)
        if detail is not None and await repository.add_unlock(
            session, user_id, a.id, clock.now(), detail or None
        ):
            added.append(a.id)
    return added


async def mark_achievement_seen(
    session: AsyncSession, user_id: uuid.UUID, achievement_id: str
) -> None:
    """POST /achievements/{id}/seen. 404 ACHIEVEMENT_NOT_FOUND unless the student unlocked it."""
    if not await repository.mark_seen(session, user_id, achievement_id, clock.now()):
        raise NotFoundError("Achievement not found", code="ACHIEVEMENT_NOT_FOUND")
    await session.commit()


# =========================================================================== settings / privacy

DEFAULT_REMINDER_TIME = time(20, 30)


def _notification_out(row: UserSettings | None) -> NotificationSettingsOut:
    reminder = row.daily_reminder_time if row is not None else None
    return NotificationSettingsOut(
        study_reminders=row.study_reminders if row is not None else True,
        reminder_time=(reminder or DEFAULT_REMINDER_TIME).strftime("%H:%M"),
        community_replies=row.community_replies if row is not None else True,
    )


def _privacy_out(row: UserSettings | None) -> PrivacySettingsOut:
    return PrivacySettingsOut(
        personalised_recommendations=True,
        improve_ai=row.improve_ai if row is not None else True,
        show_name_in_community=row.show_name_in_community if row is not None else True,
        share_research=row.share_research if row is not None else False,
    )


async def _settings_row(session: AsyncSession, user_id: uuid.UUID) -> UserSettings:
    """The student's row, created with the defaults if missing (no commit)."""
    row = await repository.get_settings_row(session, user_id)
    if row is None:
        row = UserSettings(
            user_id=user_id,
            study_reminders=True,
            community_replies=True,
            improve_ai=True,
            show_name_in_community=True,
            share_research=False,
        )
        repository.add_settings_row(session, row)
    return row


async def get_notification_settings(
    session: AsyncSession, user_id: uuid.UUID
) -> NotificationSettingsOut:
    """GET /settings. Also what a study-reminder sender must check (study_reminders and
    reminder_time)."""
    return _notification_out(await repository.get_settings_row(session, user_id))


async def update_notification_settings(
    session: AsyncSession, user_id: uuid.UUID, req: NotificationSettingsUpdate
) -> NotificationSettingsOut:
    """PATCH /settings: any subset; returns the full object."""
    row = await _settings_row(session, user_id)
    fields = req.model_fields_set
    if "study_reminders" in fields:
        row.study_reminders = bool(req.study_reminders)
    if "community_replies" in fields:
        row.community_replies = bool(req.community_replies)
    if "reminder_time" in fields and req.reminder_time is not None:
        hours, minutes = req.reminder_time.split(":")
        row.daily_reminder_time = time(int(hours), int(minutes))
    await session.commit()
    return _notification_out(row)


async def get_privacy_settings(session: AsyncSession, user_id: uuid.UUID) -> PrivacySettingsOut:
    """GET /privacy."""
    return _privacy_out(await repository.get_settings_row(session, user_id))


async def update_privacy_settings(
    session: AsyncSession, user_id: uuid.UUID, req: PrivacySettingsUpdate
) -> PrivacySettingsOut:
    """PATCH /privacy: any subset. personalised_recommendations is ignored (always on)."""
    row = await _settings_row(session, user_id)
    for field in ("improve_ai", "show_name_in_community", "share_research"):
        if field in req.model_fields_set:
            setattr(row, field, bool(getattr(req, field)))
    await session.commit()
    return _privacy_out(row)


async def wants_community_replies(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """For the community module: notify this student about replies to their posts?"""
    return (await get_notification_settings(session, user_id)).community_replies


async def users_hiding_name(session: AsyncSession, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """For the community module: authors who show as "A/L student" instead of their name."""
    return await repository.users_hiding_name(session, list(set(user_ids)))
