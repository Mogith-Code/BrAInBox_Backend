"""HTTP endpoints for the profiles module. Owner: Mogith.

    GET    /api/v1/profile/options    choices for the 3 setup steps (streams, subjects, years...)
    GET    /api/v1/profile            my profile
    PATCH  /api/v1/profile            save any subset of the setup fields
    POST   /api/v1/profile/complete   "Finish setup" (all required fields must be filled)

All need a registered user (Firebase token + POST /auth/register done).
Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.profiles import service
from api.modules.profiles.schemas import ModuleStatus, ProfileOptionsOut, ProfileOut, ProfileUpdate

router = APIRouter(tags=["Profiles"])


@router.get("/profiles/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    return await service.get_status()


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
