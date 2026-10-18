"""Make a Firebase user an admin.

Find the UID in the Firebase console (Authentication -> Users), then:

    python scripts/seed_admin.py --uid <firebase_uid> [--email someone@example.com]

Creates the users row if the person has not registered yet.
"""

import argparse
import asyncio

import _bootstrap  # noqa: F401
from sqlalchemy import select

from shared.db.models import User
from shared.db.session import SessionLocal
from shared.enums import UserRole


async def make_admin(uid: str, email: str | None) -> None:
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.firebase_uid == uid))
        ).scalar_one_or_none()
        if user is None:
            user = User(firebase_uid=uid, email=email)
            session.add(user)
            action = "Created"
        else:
            action = "Updated"
        user.role = UserRole.ADMIN
        user.is_active = True
        await session.commit()
        print(f"{action} user {uid} -> role=admin")


def main() -> None:
    parser = argparse.ArgumentParser(description="Give a Firebase user the admin role")
    parser.add_argument("--uid", required=True, help="Firebase UID")
    parser.add_argument("--email", default=None)
    args = parser.parse_args()
    asyncio.run(make_admin(args.uid, args.email))


if __name__ == "__main__":
    main()
