"""Changing Firebase Auth users from the backend (firebase-admin).

Used by the auth module to mark an email as verified, set a new password after a reset,
and delete an account. These calls need a service account (GOOGLE_APPLICATION_CREDENTIALS).

Every function is a small wrapper, so tests can replace them with monkeypatch.
"""

import logging
from typing import Any

from fastapi.concurrency import run_in_threadpool

from api.core.errors import ServiceUnavailableError
from api.core.security import _get_firebase_app

logger = logging.getLogger(__name__)


async def update_user(uid: str, **changes: Any) -> None:
    """e.g. update_user(uid, email_verified=True) or update_user(uid, password="...")."""
    from firebase_admin import auth as firebase_auth

    try:
        await run_in_threadpool(firebase_auth.update_user, uid, app=_get_firebase_app(), **changes)
    except Exception as exc:
        # Never log `changes`: it can contain a password.
        logger.error("Firebase update_user failed for %s: %s", uid, type(exc).__name__)
        raise ServiceUnavailableError(
            "Could not update the account. Please try again.", code="FIREBASE_ERROR"
        ) from exc


async def delete_user(uid: str) -> None:
    """Delete the Firebase account. An already-deleted account is not an error."""
    from firebase_admin import auth as firebase_auth

    try:
        await run_in_threadpool(firebase_auth.delete_user, uid, app=_get_firebase_app())
    except firebase_auth.UserNotFoundError:
        logger.info("Firebase user %s was already deleted", uid)
    except Exception as exc:
        logger.error("Firebase delete_user failed for %s: %s", uid, type(exc).__name__)
        raise ServiceUnavailableError(
            "Could not delete the account. Please try again.", code="FIREBASE_ERROR"
        ) from exc
