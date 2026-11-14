"""Give an existing user the admin role, by email.

    python -m scripts.make_admin someone@example.com
    docker compose exec api python -m scripts.make_admin someone@example.com

1. Finds the `users` row by email (case-insensitive) and sets role=admin + is_active=true.
2. No row yet (the person signed in to Firebase but never registered)? It looks the email up in
   Firebase (needs FIREBASE_PROJECT_ID + the service account) and creates the row.

Roles are read from OUR database on every request (api/core/security.py), not from a Firebase
custom claim, so no claim is set. Sign out and in again in the admin portal afterwards.
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

# Works as `python scripts/make_admin.py` AND `python -m scripts.make_admin`
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from shared.db.models import User  # noqa: E402
from shared.db.session import SessionLocal  # noqa: E402
from shared.enums import UserRole  # noqa: E402

# email -> (firebase uid, display name), or None if Firebase has no such user
FirebaseLookup = Callable[[str], Awaitable[tuple[str, str | None] | None]]


async def firebase_lookup(email: str) -> tuple[str, str | None] | None:
    """Find a Firebase user by email (firebase-admin)."""
    from fastapi.concurrency import run_in_threadpool
    from firebase_admin import auth as firebase_auth

    from api.core.security import _get_firebase_app

    try:
        record = await run_in_threadpool(
            firebase_auth.get_user_by_email, email, app=_get_firebase_app()
        )
    except firebase_auth.UserNotFoundError:
        return None
    return record.uid, record.display_name


async def make_admin(
    session: AsyncSession, email: str, lookup: FirebaseLookup = firebase_lookup
) -> str:
    """Make the user with this email an admin. Returns a short message; raises LookupError."""
    email = email.strip().lower()
    user = (
        await session.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()
    if user is None:
        found = await lookup(email)
        if found is None:
            raise LookupError(
                f"No user with email {email}. Sign in once in the app (or Firebase) first."
            )
        uid, name = found
        user = User(firebase_uid=uid, email=email, display_name=name, email_verified=True)
        session.add(user)
        action = "Created"
    else:
        action = "Updated"
    user.role = UserRole.ADMIN
    user.is_active = True
    user.disabled_at = None
    await session.commit()
    return f"{action} {email} -> role=admin"


async def _main(email: str) -> int:
    async with SessionLocal() as session:
        try:
            print(await make_admin(session, email))
        except LookupError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Give an existing user the admin role")
    parser.add_argument("email", help="the user's email address")
    raise SystemExit(asyncio.run(_main(parser.parse_args().email)))


if __name__ == "__main__":
    main()
