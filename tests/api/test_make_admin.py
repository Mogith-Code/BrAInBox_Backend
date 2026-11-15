"""scripts/make_admin.py: give an existing user the admin role by email."""

import pytest
from sqlalchemy import delete, select

from scripts.make_admin import make_admin
from shared.db.models import User
from shared.enums import UserRole

pytestmark = pytest.mark.db

EMAIL = "make.admin@test.local"


@pytest.fixture
async def clean(db_session):  # type: ignore[no-untyped-def]
    await db_session.execute(delete(User).where(User.email == EMAIL))
    await db_session.commit()
    yield
    await db_session.rollback()
    await db_session.execute(delete(User).where(User.email == EMAIL))
    await db_session.commit()


async def no_firebase(email: str):  # type: ignore[no-untyped-def]
    return None


async def test_existing_user_becomes_admin(db_session, clean) -> None:  # type: ignore[no-untyped-def]
    db_session.add(User(firebase_uid="uid-make-admin", email=EMAIL, is_active=False))
    await db_session.commit()

    message = await make_admin(db_session, "  Make.Admin@TEST.local ", lookup=no_firebase)

    user = (await db_session.execute(select(User).where(User.email == EMAIL))).scalar_one()
    assert message.startswith("Updated")
    assert (user.role, user.is_active) == (UserRole.ADMIN, True)


async def test_firebase_only_user_gets_a_row(db_session, clean) -> None:  # type: ignore[no-untyped-def]
    async def firebase(email: str):  # type: ignore[no-untyped-def]
        return ("uid-from-firebase", "Admin Amara")

    message = await make_admin(db_session, EMAIL, lookup=firebase)

    user = (await db_session.execute(select(User).where(User.email == EMAIL))).scalar_one()
    assert message.startswith("Created")
    assert (user.firebase_uid, user.role, user.display_name) == (
        "uid-from-firebase",
        UserRole.ADMIN,
        "Admin Amara",
    )


async def test_unknown_email_is_an_error(db_session, clean) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(LookupError):
        await make_admin(db_session, EMAIL, lookup=no_firebase)
