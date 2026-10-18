"""Authentication (Firebase ID tokens) and role checks.

The mobile app / admin portal sends:  Authorization: Bearer <Firebase ID token>

Dependencies you can use in routers:
    claims: FirebaseClaimsDep      -> token is valid (user may not be registered yet)
    user:   CurrentUserDep         -> token is valid AND the user exists in our DB
    dependencies=[Depends(require_role(UserRole.ADMIN))]  -> admins only
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from api.core.config import get_settings
from api.core.database import SessionDep
from api.core.errors import ForbiddenError, ServiceUnavailableError, UnauthorizedError
from shared.db.models import User
from shared.enums import UserRole

logger = logging.getLogger(__name__)

# auto_error=False -> we raise our own error format instead of FastAPI's default.
bearer_scheme = HTTPBearer(auto_error=False, description="Firebase ID token")

_firebase_app: Any = None


@dataclass
class CurrentUser:
    """The logged-in user, as seen by routers and services."""

    id: uuid.UUID
    firebase_uid: str
    email: str | None
    role: UserRole

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN


def _get_firebase_app() -> Any:
    """Initialise firebase-admin once (lazily, so the app starts without credentials)."""
    global _firebase_app
    if _firebase_app is None:
        import firebase_admin

        settings = get_settings()
        if not settings.FIREBASE_PROJECT_ID:
            raise ServiceUnavailableError(
                "Firebase is not configured (FIREBASE_PROJECT_ID is empty)",
                code="AUTH_NOT_CONFIGURED",
            )
        # Uses GOOGLE_APPLICATION_CREDENTIALS if set. Verifying tokens only needs the project id.
        _firebase_app = firebase_admin.initialize_app(
            options={"projectId": settings.FIREBASE_PROJECT_ID}, name="brainbox-api"
        )
    return _firebase_app


async def get_firebase_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> dict[str, Any]:
    """Verify the Firebase ID token and return its claims (uid, email, ...)."""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Missing bearer token")

    from firebase_admin import auth as firebase_auth

    app = _get_firebase_app()
    try:
        # verify_id_token is blocking (it may download Google's public keys).
        claims: dict[str, Any] = await run_in_threadpool(
            firebase_auth.verify_id_token, credentials.credentials, app
        )
    except Exception as exc:  # expired, revoked, wrong project, malformed...
        logger.info("Invalid Firebase token: %s", exc)
        raise UnauthorizedError("Invalid or expired token", code="INVALID_TOKEN") from exc
    return claims


FirebaseClaimsDep = Annotated[dict[str, Any], Depends(get_firebase_claims)]


async def get_current_user(claims: FirebaseClaimsDep, session: SessionDep) -> CurrentUser:
    """Return the registered, active user for this token."""
    result = await session.execute(select(User).where(User.firebase_uid == claims["uid"]))
    user = result.scalar_one_or_none()
    if user is None:
        raise UnauthorizedError(
            "User is not registered. Call POST /api/v1/auth/register first.",
            code="USER_NOT_REGISTERED",
        )
    if not user.is_active:
        raise ForbiddenError("This account is disabled", code="USER_DISABLED")
    return CurrentUser(id=user.id, firebase_uid=user.firebase_uid, email=user.email, role=user.role)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_role(*roles: UserRole) -> Callable[..., Awaitable[CurrentUser]]:
    """Dependency factory: only users with one of `roles` may continue.

    Example: APIRouter(dependencies=[Depends(require_role(UserRole.ADMIN))])
    """

    async def checker(user: CurrentUserDep) -> CurrentUser:
        if user.role not in roles:
            raise ForbiddenError("You do not have permission to do this")
        return user

    return checker


AdminUserDep = Annotated[CurrentUser, Depends(require_role(UserRole.ADMIN))]
