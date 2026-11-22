"""HTTP endpoints for the profiles module. Owner: Mogith.

    GET    /api/v1/profile/options    choices for the 3 setup steps (streams, subjects, years...)
    GET    /api/v1/profile            my profile
    PATCH  /api/v1/profile            save any subset of the setup fields
    POST   /api/v1/profile/complete   "Finish setup" (all required fields must be filled)
    GET    /api/v1/profile/overview   the Profile page: goal, stats, achievements
    POST   /api/v1/achievements/{id}/seen   the "Achievement unlocked" pop-up was shown

Settings (`settings_router`, tag "Settings"):
    GET    /api/v1/settings           Settings > Notifications
    PATCH  /api/v1/settings           any subset of the notification switches
    GET    /api/v1/privacy            Data & privacy
    PATCH  /api/v1/privacy            any subset of the privacy switches

All need a registered user (Firebase token + POST /auth/register done).
Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter, Response, status

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.profiles import service
from api.modules.profiles.schemas import (
    NotificationSettingsOut,
    NotificationSettingsUpdate,
    PrivacySettingsOut,
    PrivacySettingsUpdate,
    ProfileOptionsOut,
    ProfileOut,
    ProfileOverviewOut,
    ProfileUpdate,
)

router = APIRouter(tags=["Profiles"])
settings_router = APIRouter(tags=["Settings"])


@router.get(
    "/profile/options",
    response_model=ProfileOptionsOut,
    summary="Choices for profile setup (streams, subjects, exam years, grades, times)",
)
async def get_options(user: CurrentUserDep) -> ProfileOptionsOut:
    return service.get_options()


@router.get("/profile", response_model=ProfileOut, summary="My profile")
async def get_profile(user: CurrentUserDep, session: SessionDep) -> ProfileOut:
    return await service.get_profile(session, user.id)


@router.patch("/profile", response_model=ProfileOut, summary="Save profile setup fields")
async def update_profile(
    req: ProfileUpdate, user: CurrentUserDep, session: SessionDep
) -> ProfileOut:
    """Validation: subject must be available, confidence 0–100, hours_per_day 0.5–6 in
    0.5 steps, study_days at least one of mon..sun, exam_year from /profile/options."""
    return await service.update_profile(session, user.id, req)


@router.post("/profile/complete", response_model=ProfileOut, summary="Finish profile setup")
async def complete_profile(user: CurrentUserDep, session: SessionDep) -> ProfileOut:
    return await service.complete_profile(session, user.id)


@router.get(
    "/profile/overview",
    response_model=ProfileOverviewOut,
    summary="The Profile page: goal, streak, questions answered, topics mastered, achievements",
)
async def get_overview(user: CurrentUserDep, session: SessionDep) -> ProfileOverviewOut:
    """Locked achievements are listed too (after the unlocked ones, newest unlocked first).
    `days_to_exam` is null until the exam year and its A/L date (AL_EXAM_DATES) are known."""
    return await service.get_overview(session, user)


@router.post(
    "/achievements/{achievement_id}/seen",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark an unlocked achievement as seen (its pop-up was shown)",
)
async def mark_achievement_seen(
    achievement_id: str, user: CurrentUserDep, session: SessionDep
) -> Response:
    """404 ACHIEVEMENT_NOT_FOUND if the id is unknown or the student hasn't unlocked it."""
    await service.mark_achievement_seen(session, user.id, achievement_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- settings / privacy


@settings_router.get(
    "/settings", response_model=NotificationSettingsOut, summary="My notification settings"
)
async def get_settings(user: CurrentUserDep, session: SessionDep) -> NotificationSettingsOut:
    """Defaults: study_reminders true, reminder_time "20:30" (Sri Lanka), community_replies
    true."""
    return await service.get_notification_settings(session, user.id)


@settings_router.patch(
    "/settings", response_model=NotificationSettingsOut, summary="Change notification settings"
)
async def update_settings(
    req: NotificationSettingsUpdate, user: CurrentUserDep, session: SessionDep
) -> NotificationSettingsOut:
    """Any subset of the fields (not null). reminder_time is 24 h "HH:mm"."""
    return await service.update_notification_settings(session, user.id, req)


@settings_router.get("/privacy", response_model=PrivacySettingsOut, summary="My privacy choices")
async def get_privacy(user: CurrentUserDep, session: SessionDep) -> PrivacySettingsOut:
    """personalised_recommendations is always true. Defaults: improve_ai true,
    show_name_in_community true, share_research false."""
    return await service.get_privacy_settings(session, user.id)


@settings_router.patch(
    "/privacy", response_model=PrivacySettingsOut, summary="Change privacy choices"
)
async def update_privacy(
    req: PrivacySettingsUpdate, user: CurrentUserDep, session: SessionDep
) -> PrivacySettingsOut:
    """Any subset (not null). personalised_recommendations can't be turned off (ignored).
    show_name_in_community=false shows "A/L student" instead of your name in the community."""
    return await service.update_privacy_settings(session, user.id, req)
