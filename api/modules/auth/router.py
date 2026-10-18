"""HTTP endpoints for the auth module. Owner: Mogith.

Planned endpoints (details in README.md):
    POST   /api/v1/auth/register                           Create the users row for a new Firebase account (uses FirebaseClaimsDep, not CurrentUserDep)
    GET    /api/v1/auth/me                                 Current user
    PATCH  /api/v1/auth/me                                 Update display name etc.
    DELETE /api/v1/auth/me                                 Delete / anonymise the account

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter

from api.core.security import CurrentUserDep
from api.modules.auth import service
from api.modules.auth.schemas import ModuleStatus

router = APIRouter(tags=["Auth"])


@router.get("/auth/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    # TODO(Mogith): replace this placeholder with the real endpoints listed above.
    return await service.get_status()
