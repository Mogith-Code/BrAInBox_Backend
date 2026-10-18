"""Auth: register / me, 6-digit email codes, password reset. Owner: Mogith."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from api.core.config import get_settings
from api.core.errors import AppError
from api.modules.auth.service import check_password_policy, hash_secret, normalize_phone
from shared.db.models import EmailCode, PasswordResetToken, User
from tests.conftest import STUDENT, delete_test_user, make_api_client, student_claims

# --------------------------------------------------------------------------- no database


async def test_auth_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/auth/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_auth_status_placeholder(client):
    response = await client.get("/api/v1/auth/status")
    assert response.json() == {"module": "auth", "status": "todo"}


@pytest.mark.parametrize(
    "raw",
    ["077 123 4567", "0771234567", "771234567", "94771234567", "+94 77 123-4567", "(077) 123 4567"],
)
def test_phone_is_normalised_to_e164(raw):
    assert normalize_phone(raw) == "+94771234567"


@pytest.mark.parametrize("raw", ["011 234 5678", "+44 7700 900123", "07712", "abc"])
def test_invalid_phone_is_rejected(raw):
    with pytest.raises(AppError) as err:
        normalize_phone(raw)
    assert err.value.code == "INVALID_PHONE"


def test_empty_phone_means_no_phone():
    assert normalize_phone(None) is None
    assert normalize_phone("  ") is None


@pytest.mark.parametrize("password", ["short1", "abcdefgh", "12345678"])
def test_weak_passwords(password):
    with pytest.raises(AppError) as err:
        check_password_policy(password)
    assert err.value.code == "WEAK_PASSWORD"


def test_good_password():
    check_password_policy("Nirma2027")


async def test_reset_send_validates_email(anon_client):
    response = await anon_client.post("/api/v1/auth/password-reset/send", json={"email": "nope"})
    assert response.status_code == 422


# --------------------------------------------------------------------------- register / me


@pytest.fixture
async def no_student(db_session):
    """Make sure the test student does NOT exist yet (and clean up afterwards)."""
    await delete_test_user(db_session)
    yield
    await delete_test_user(db_session)


@pytest.mark.db
async def test_register_creates_then_updates(no_student):
    body = {"full_name": "Nethmi Perera", "phone": "077 123 4567", "consent": True}
    async with make_api_client(claims=student_claims()) as c:
        before = await c.get("/api/v1/auth/me")
        created = await c.post("/api/v1/auth/register", json=body)
        again = await c.post("/api/v1/auth/register", json={**body, "full_name": "Nethmi P."})
        me = await c.get("/api/v1/auth/me")

    assert before.status_code == 404
    assert before.json()["error"]["code"] == "USER_NOT_FOUND"
    assert created.status_code == 201
    user = created.json()
    assert user["full_name"] == "Nethmi Perera"
    assert user["phone"] == "+94771234567"
    assert user["email"] == STUDENT.email
    assert user["role"] == "student"
    assert user["email_verified"] is False
    assert user["onboarding"] == {
        "profile_completed": False,
        "diagnostic_completed": False,
        "diagnostic_skipped": False,
    }
    assert again.status_code == 200  # upsert: same Firebase uid -> same row
    assert again.json()["id"] == user["id"]
    assert me.json()["full_name"] == "Nethmi P."


@pytest.mark.db
async def test_register_requires_consent_and_valid_phone(no_student):
    async with make_api_client(claims=student_claims()) as c:
        no_consent = await c.post(
            "/api/v1/auth/register", json={"full_name": "N", "consent": False}
        )
        bad_phone = await c.post(
            "/api/v1/auth/register", json={"full_name": "N", "phone": "12", "consent": True}
        )
    assert no_consent.json()["error"]["code"] == "CONSENT_REQUIRED"
    assert bad_phone.json()["error"]["code"] == "INVALID_PHONE"


@pytest.mark.db
async def test_google_users_are_verified_from_the_token(no_student):
    async with make_api_client(claims=student_claims(email_verified=True)) as c:
        response = await c.post("/api/v1/auth/register", json={"full_name": "N", "consent": True})
    assert response.json()["email_verified"] is True


@pytest.mark.db
async def test_update_and_delete_me(student_in_db, fake_firebase, db_session):
    async with make_api_client(claims=student_claims()) as c:
        updated = await c.patch("/api/v1/auth/me", json={"phone": "0711111111"})
        removed = await c.patch("/api/v1/auth/me", json={"phone": None})
        deleted = await c.delete("/api/v1/auth/me")
    assert updated.json()["phone"] == "+94711111111"
    assert removed.json()["phone"] is None
    assert deleted.status_code == 204
    assert ("delete_user", STUDENT.firebase_uid, {}) in fake_firebase
    assert await db_session.get(User, STUDENT.id) is None


# --------------------------------------------------------------------------- email verification


@pytest.mark.db
async def test_email_code_verifies_the_email(student_in_db, fake_email, fake_firebase):
    async with make_api_client(user=STUDENT, email=fake_email) as c:
        sent = await c.post("/api/v1/auth/email-code/send")
        verified = await c.post(
            "/api/v1/auth/email-code/verify", json={"code": fake_email.last_code()}
        )
        again = await c.post("/api/v1/auth/email-code/send")

    assert sent.status_code == 200
    assert sent.json() == {"sent": True, "resend_in": 60, "expires_in": 600}  # no dev_code
    assert fake_email.sent[0].subject == "Your BrAInBox code"
    assert fake_email.sent[0].to == STUDENT.email
    assert verified.status_code == 200
    assert verified.json()["email_verified"] is True
    assert ("update_user", STUDENT.firebase_uid, {"email_verified": True}) in fake_firebase
    assert again.json()["error"]["code"] == "ALREADY_VERIFIED"


@pytest.mark.db
async def test_code_is_stored_hashed(student_in_db, fake_email, db_session):
    async with make_api_client(user=STUDENT, email=fake_email) as c:
        await c.post("/api/v1/auth/email-code/send")
    code = fake_email.last_code()
    row = (await db_session.execute(select(EmailCode))).scalars().one()
    assert row.code_hash == hash_secret("verify_email", code)
    assert code not in row.code_hash
    assert row.expires_at - row.created_at == timedelta(minutes=10)


@pytest.mark.db
async def test_wrong_codes_count_and_sixth_try_is_blocked(student_in_db, fake_email):
    async with make_api_client(user=STUDENT, email=fake_email) as c:
        await c.post("/api/v1/auth/email-code/send")
        right = fake_email.last_code()
        wrong = "000000" if right != "000000" else "111111"
        results = [
            (await c.post("/api/v1/auth/email-code/verify", json={"code": wrong})).json()
            for _ in range(5)
        ]
        sixth = await c.post("/api/v1/auth/email-code/verify", json={"code": right})

    assert [r["error"]["code"] for r in results] == ["CODE_INVALID"] * 5
    assert [r["error"]["attempts_left"] for r in results] == [4, 3, 2, 1, 0]
    assert sixth.status_code == 429
    assert sixth.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"


@pytest.mark.db
async def test_expired_code_fails(student_in_db, fake_email, db_session):
    async with make_api_client(user=STUDENT, email=fake_email) as c:
        await c.post("/api/v1/auth/email-code/send")
        await db_session.execute(
            update(EmailCode).values(expires_at=EmailCode.created_at - timedelta(seconds=1))
        )
        await db_session.commit()
        response = await c.post(
            "/api/v1/auth/email-code/verify", json={"code": fake_email.last_code()}
        )
    assert response.json()["error"]["code"] == "CODE_EXPIRED"


@pytest.mark.db
async def test_resend_cooldown_and_new_code_cancels_old(student_in_db, fake_email, db_session):
    async with make_api_client(user=STUDENT, email=fake_email) as c:
        await c.post("/api/v1/auth/email-code/send")
        first_code = fake_email.last_code()
        too_soon = await c.post("/api/v1/auth/email-code/send")

        # pretend 61 seconds passed
        await db_session.execute(
            update(EmailCode).values(created_at=EmailCode.created_at - timedelta(seconds=61))
        )
        await db_session.commit()
        resent = await c.post("/api/v1/auth/email-code/send")
        old = await c.post("/api/v1/auth/email-code/verify", json={"code": first_code})

    assert too_soon.status_code == 429
    error = too_soon.json()["error"]
    assert error["code"] == "RESEND_TOO_SOON"
    assert 0 < error["retry_after"] <= 60
    assert too_soon.headers["Retry-After"] == str(error["retry_after"])
    assert resent.status_code == 200
    if first_code != fake_email.last_code():  # (1 in a million: same digits twice)
        assert old.json()["error"]["code"] == "CODE_INVALID"


# --------------------------------------------------------------------------- password reset


@pytest.mark.db
async def test_password_reset_end_to_end(student_in_db, fake_email, fake_firebase):
    async with make_api_client(email=fake_email) as c:
        sent = await c.post(
            "/api/v1/auth/password-reset/send", json={"email": "Student@Test.local"}
        )
        verified = await c.post(
            "/api/v1/auth/password-reset/verify",
            json={"email": STUDENT.email, "code": fake_email.last_code()},
        )
        token = verified.json()["reset_token"]
        weak = await c.post(
            "/api/v1/auth/password-reset/complete",
            json={"reset_token": token, "new_password": "password"},
        )
        done = await c.post(
            "/api/v1/auth/password-reset/complete",
            json={"reset_token": token, "new_password": "Nirma2027"},
        )
        reused = await c.post(
            "/api/v1/auth/password-reset/complete",
            json={"reset_token": token, "new_password": "Nirma2028"},
        )

    assert sent.json() == {"sent": True, "resend_in": 60, "expires_in": 600}
    assert verified.json()["expires_in"] == 600
    assert weak.json()["error"]["code"] == "WEAK_PASSWORD"  # token still usable after this
    assert done.json() == {"reset": True}
    assert ("update_user", STUDENT.firebase_uid, {"password": "Nirma2027"}) in fake_firebase
    assert reused.json()["error"]["code"] == "RESET_TOKEN_INVALID"  # single use


@pytest.mark.db
async def test_unknown_email_looks_the_same(fake_email, db_session):
    email = "nobody@test.local"
    async with make_api_client(email=fake_email) as c:
        response = await c.post("/api/v1/auth/password-reset/send", json={"email": email})
        too_soon = await c.post("/api/v1/auth/password-reset/send", json={"email": email})
    assert response.status_code == 200
    assert response.json() == {"sent": True, "resend_in": 60, "expires_in": 600}
    assert fake_email.sent == []  # nothing is emailed to unknown addresses
    assert too_soon.json()["error"]["code"] == "RESEND_TOO_SOON"  # same cooldown as real users
    await delete_test_user(db_session)


@pytest.mark.db
async def test_reset_token_expires(student_in_db, fake_email, fake_firebase, db_session):
    async with make_api_client(email=fake_email) as c:
        await c.post("/api/v1/auth/password-reset/send", json={"email": STUDENT.email})
        verified = await c.post(
            "/api/v1/auth/password-reset/verify",
            json={"email": STUDENT.email, "code": fake_email.last_code()},
        )
        await db_session.execute(
            update(PasswordResetToken).values(
                expires_at=PasswordResetToken.created_at - timedelta(seconds=1)
            )
        )
        await db_session.commit()
        response = await c.post(
            "/api/v1/auth/password-reset/complete",
            json={"reset_token": verified.json()["reset_token"], "new_password": "Nirma2027"},
        )
    assert response.json()["error"]["code"] == "RESET_TOKEN_INVALID"
    assert fake_firebase == []


# --------------------------------------------------------------------------- dev_code


@pytest.mark.db
@pytest.mark.parametrize(
    ("environment", "expose", "shown"),
    [("dev", True, True), ("dev", False, False), ("test", True, False), ("prod", True, False)],
)
async def test_dev_code_only_in_dev_with_flag(
    environment, expose, shown, monkeypatch, fake_email, db_session
):
    settings = get_settings()
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(settings, "DEV_EXPOSE_CODES", expose)
    async with make_api_client(email=fake_email) as c:
        response = await c.post(
            "/api/v1/auth/password-reset/send", json={"email": "devcode@test.local"}
        )
    assert ("dev_code" in response.json()) is shown
    if shown:
        assert response.json()["dev_code"].isdigit() and len(response.json()["dev_code"]) == 6
    await delete_test_user(db_session)
