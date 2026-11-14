"""Admin Students: GET /admin/users and PATCH /admin/users/{id}. Owner: Mogith."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from api.core import clock, firebase_users
from shared.db.models import AuditLog, StudentProfile, StudyActivity, Unit, UnitMastery, User
from shared.enums import UserRole
from tests.conftest import ADMIN

URL = "/api/v1/admin/users"
TAG = "adminusers"  # every test student's email contains this, so searches stay isolated


@pytest.fixture
def firebase_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    calls: list[tuple[str, bool]] = []

    async def set_disabled(uid: str, disabled: bool) -> None:
        calls.append((uid, disabled))

    monkeypatch.setattr(firebase_users, "set_disabled", set_disabled)
    return calls


@pytest.fixture
async def students(db_session, admin_in_db):  # type: ignore[no-untyped-def]
    """Four students: active with mastery, inactive (40 days), suspended, active in Kandy."""
    today = clock.today()
    unit = Unit(number=700_000 + uuid.uuid4().int % 99_999, title="Genetics")
    db_session.add(unit)
    rows = {}
    for key, name, active in [
        ("nethmi", "Nethmi Perera", True),
        ("tharindu", "Tharindu Bandara", True),
        ("ruwan", "Ruwan Jayasinghe", False),
        ("kavindu", "Kavindu Silva", True),
    ]:
        user = User(
            firebase_uid=f"uid-{TAG}-{key}",
            email=f"{key}.{TAG}@test.local",
            display_name=name,
            role=UserRole.STUDENT,
            is_active=active,
        )
        db_session.add(user)
        rows[key] = user
    await db_session.flush()
    for key, school, district, year in [
        ("nethmi", "Visakha V.", "Colombo", 2027),
        ("tharindu", "Rahula C.", "Matara", 2026),
        ("ruwan", "Maliyadeva", "Kurunegala", 2027),
        ("kavindu", "Trinity C.", "Kandy", 2027),
    ]:
        db_session.add(
            StudentProfile(user_id=rows[key].id, school=school, district=district, exam_year=year)
        )
    nethmi_id = rows["nethmi"].id
    db_session.add_all(
        [
            StudyActivity(user_id=nethmi_id, activity_date=today),
            StudyActivity(user_id=rows["kavindu"].id, activity_date=today - timedelta(days=3)),
            StudyActivity(user_id=rows["tharindu"].id, activity_date=today - timedelta(days=40)),
            StudyActivity(user_id=rows["ruwan"].id, activity_date=today),
            UnitMastery(
                user_id=nethmi_id,
                unit_id=unit.id,
                mastery=60,
                source="diagnostic",
                created_at=clock.now() - timedelta(days=2),
            ),
            UnitMastery(user_id=nethmi_id, unit_id=unit.id, mastery=74, source="quiz"),
        ]
    )
    await db_session.commit()
    unit_id = unit.id
    yield rows
    await db_session.rollback()
    await db_session.execute(delete(User).where(User.email.like(f"%{TAG}%")))
    await db_session.execute(delete(Unit).where(Unit.id == unit_id))
    await db_session.commit()


# --------------------------------------------------------------------------- auth + validation


async def test_need_login(anon_client) -> None:
    assert (await anon_client.get(URL)).status_code == 401
    patch = await anon_client.patch(f"{URL}/{uuid.uuid4()}", json={"is_active": False})
    assert patch.status_code == 401


async def test_students_are_forbidden(client) -> None:
    listing = await client.get(URL)
    patch = await client.patch(f"{URL}/{uuid.uuid4()}", json={"is_active": False})
    assert (listing.status_code, patch.status_code) == (403, 403)
    assert listing.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("query", ["status=asleep", "page=0", "page_size=101", "exam_year=soon"])
async def test_bad_query_is_422(admin_client, query: str) -> None:
    response = await admin_client.get(f"{URL}?{query}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_bad_patch_is_422(admin_client) -> None:
    assert (await admin_client.patch(f"{URL}/{uuid.uuid4()}", json={})).status_code == 422
    assert (await admin_client.patch(f"{URL}/nope", json={"is_active": True})).status_code == 422


# --------------------------------------------------------------------------- list


@pytest.mark.db
async def test_list_shape_status_and_mastery(admin_client, students) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.get(URL, params={"search": TAG})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "active_total"}
    by_name = {s["full_name"]: s for s in body["items"]}
    assert body["total"] == 4
    assert body["active_total"] == 2  # Nethmi + Kavindu
    nethmi = by_name["Nethmi Perera"]
    assert set(nethmi) == {
        "id", "full_name", "email", "school", "district", "exam_year", "avg_mastery", "status",
        "last_active_at",
    }  # fmt: skip
    assert (nethmi["status"], nethmi["avg_mastery"], nethmi["school"]) == (
        "active",
        74,  # the newest value, not the average of the history
        "Visakha V.",
    )
    assert nethmi["last_active_at"] is not None
    assert by_name["Tharindu Bandara"]["status"] == "inactive"
    assert by_name["Ruwan Jayasinghe"]["status"] == "suspended"  # suspended wins
    assert by_name["Kavindu Silva"]["avg_mastery"] is None


@pytest.mark.db
async def test_filters_and_paging(admin_client, students) -> None:  # type: ignore[no-untyped-def]
    async def names(**params):  # type: ignore[no-untyped-def]
        params.setdefault("search", TAG)
        body = (await admin_client.get(URL, params=params)).json()
        return sorted(s["full_name"] for s in body["items"]), body

    assert (await names(search="NETHMI"))[0] == ["Nethmi Perera"]
    assert (await names(search=f"kavindu.{TAG}"))[0] == ["Kavindu Silva"]  # email match
    assert (await names(status="inactive"))[0] == ["Tharindu Bandara"]
    assert (await names(status="suspended"))[0] == ["Ruwan Jayasinghe"]
    assert (await names(district="kandy"))[0] == ["Kavindu Silva"]
    assert (await names(exam_year=2026))[0] == ["Tharindu Bandara"]
    page, body = await names(page=2, page_size=3)
    assert len(page) == 1 and body["total"] == 4
    _, suspended = await names(status="suspended")
    assert suspended["active_total"] == 2  # not changed by the status filter


@pytest.mark.db
async def test_admins_are_not_listed(admin_client, students) -> None:  # type: ignore[no-untyped-def]
    body = (await admin_client.get(URL, params={"search": "admin@test.local"})).json()
    assert body["items"] == []


# --------------------------------------------------------------------------- suspend / reinstate


@pytest.mark.db
async def test_suspend_and_reinstate(admin_client, students, firebase_calls, db_session) -> None:  # type: ignore[no-untyped-def]
    nethmi = students["nethmi"]
    suspended = await admin_client.patch(f"{URL}/{nethmi.id}", json={"is_active": False})
    reinstated = await admin_client.patch(f"{URL}/{nethmi.id}", json={"is_active": True})

    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"
    assert suspended.json()["avg_mastery"] == 74
    assert reinstated.json()["status"] == "active"
    assert firebase_calls == [(nethmi.firebase_uid, True), (nethmi.firebase_uid, False)]
    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(AuditLog.target_id == str(nethmi.id))
            )
        )
        .scalars()
        .all()
    )
    assert sorted(actions) == ["user.reinstate", "user.suspend"]


@pytest.mark.db
async def test_suspended_user_gets_user_disabled(students) -> None:  # type: ignore[no-untyped-def]
    """The existing USER_DISABLED flow: get_current_user refuses a disabled account."""
    from api.core.errors import ForbiddenError
    from api.core.security import get_current_user
    from shared.db.session import SessionLocal

    async with SessionLocal() as session:
        with pytest.raises(ForbiddenError) as err:
            await get_current_user({"uid": students["ruwan"].firebase_uid}, session)
    assert err.value.code == "USER_DISABLED"


@pytest.mark.db
async def test_cannot_suspend_self_and_unknown_is_404(
    admin_client, admin_in_db, firebase_calls
) -> None:  # type: ignore[no-untyped-def]
    myself = await admin_client.patch(f"{URL}/{ADMIN.id}", json={"is_active": False})
    unknown = await admin_client.patch(f"{URL}/{uuid.uuid4()}", json={"is_active": False})

    assert myself.status_code == 400
    assert myself.json()["error"]["code"] == "CANNOT_SUSPEND_SELF"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "USER_NOT_FOUND"
    assert firebase_calls == []
