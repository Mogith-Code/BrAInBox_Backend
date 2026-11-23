"""Business logic for the auth module. Owner: Mogith.

Firebase Auth signs users in on the phone (email/password or Google). The backend:
  * keeps a `users` row per Firebase account (register / me / update / delete)
  * creates, emails and checks 6-digit codes - for email verification after sign-up and
    for "forgot password" (our designs use codes, Firebase's own emails use links)
  * after a correct reset code, gives a single-use reset_token; with it the app sends the new
    password and we set it in Firebase. Passwords are NEVER stored in our database.

Code rules: 6 random digits (secrets), stored only as HMAC-SHA256 hash, valid 10 minutes,
max 5 wrong tries, 60-second resend cooldown, a new code cancels older ones.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service, never its repository.
"""

import hashlib
import hmac
import logging
import math
import re
import secrets
from datetime import date, timedelta
from typing import Any

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock, firebase_users, storage
from api.core.config import get_settings
from api.core.email import EmailSender, build_code_email
from api.core.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    TooManyRequestsError,
)
from api.modules.auth import repository
from api.modules.auth.schemas import (
    AdminStudentOut,
    AdminStudentPage,
    CodeSentOut,
    ModuleStatus,
    OnboardingOut,
    RegisterRequest,
    ResetTokenOut,
    UpdateMeRequest,
    UserOut,
)
from api.modules.community import service as community_service
from api.modules.content import service as content_service
from api.modules.evaluation import service as evaluation_service
from api.modules.exams import service as exams_service
from api.modules.jobs import service as jobs_service
from api.modules.learn import service as learn_service
from api.modules.notifications import service as notifications_service
from api.modules.performance import service as performance_service
from api.modules.profiles import service as profiles_service
from api.modules.quality import service as quality_service
from api.modules.quizzes import service as quizzes_service
from api.modules.recommendations import service as recommendations_service
from api.modules.visuals import service as visuals_service
from shared.db.models import EmailCode, PasswordResetToken, User

logger = logging.getLogger(__name__)

MODULE_NAME = "auth"

# DELETE /auth/me asks each of these modules to delete the student's rows, in this order.
# Each has `delete_user_data(session, user_id) -> list[storage paths]` and does not commit.
# Only the auth tables (email codes, reset tokens) go with the users row itself. Columns with
# ON DELETE SET NULL are shared content the student only touched (e.g. an approved visual they
# asked for, ai_usage_log for cost reports): they stay without the link to the student.
USER_DATA_SERVICES = (
    evaluation_service,  # evaluations + answer photos
    exams_service,  # quiz / exam / diagnostic attempts, answers, personal papers
    recommendations_service,  # study plan + items, daily plan, recommendations
    performance_service,  # mistakes journal, mastery, activity
    content_service,  # uploads + summaries, own notes, library
    learn_service,  # bookmarks + Learn upload files
    community_service,  # posts, replies, votes, reports, group memberships
    quality_service,  # question reports
    visuals_service,  # visual reports, own unapproved visuals + their images
    notifications_service,  # notifications, push device tokens
    jobs_service,  # AI jobs the student started
    profiles_service,  # profile + settings
)

VERIFY_EMAIL = "verify_email"
RESET_PASSWORD = "reset_password"
CODE_TTL_SECONDS = 600  # 10 minutes
RESEND_COOLDOWN_SECONDS = 60
MAX_WRONG_ATTEMPTS = 5
RESET_TOKEN_TTL_SECONDS = 600


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


async def count_active_students(session: AsyncSession) -> int:
    """Student accounts that are not suspended."""
    return await repository.count_active_students(session)


# =========================================================================== small helpers


def normalize_email(email: str | None) -> str | None:
    return email.strip().lower() if email else None


_PHONE_SEPARATORS = re.compile(r"[\s\-().]")
_SL_MOBILE = re.compile(r"^\+947\d{8}$")


def normalize_phone(raw: str | None) -> str | None:
    """Sri Lankan mobile -> E.164. "077 123 4567", "0771234567", "94771234567" and
    "+94 77 123 4567" all become "+94771234567". Empty -> None. Anything else -> INVALID_PHONE.
    """
    if raw is None or not raw.strip():
        return None
    digits = _PHONE_SEPARATORS.sub("", raw.strip())
    if digits.startswith("+"):
        candidate = digits
    elif digits.startswith("94"):
        candidate = "+" + digits
    elif digits.startswith("0"):
        candidate = "+94" + digits[1:]
    else:
        candidate = "+94" + digits
    if not _SL_MOBILE.match(candidate):
        raise AppError("Enter a Sri Lankan mobile number, e.g. 077 123 4567", code="INVALID_PHONE")
    return candidate


def check_password_policy(password: str) -> None:
    """At least 8 characters, with at least one letter and one number."""
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise AppError(
            "Use at least 8 characters with at least one letter and one number",
            code="WEAK_PASSWORD",
        )


def hash_secret(purpose: str, value: str) -> str:
    """HMAC-SHA256 with the server secret. The raw code / token is never stored."""
    key = get_settings().AUTH_CODE_SECRET.encode()
    return hmac.new(key, f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def new_code() -> str:
    """6 random digits, e.g. "048213"."""
    return f"{secrets.randbelow(1_000_000):06d}"


def dev_code_allowed() -> bool:
    """dev_code is returned ONLY in the dev environment with DEV_EXPOSE_CODES=true."""
    settings = get_settings()
    return settings.ENVIRONMENT == "dev" and settings.DEV_EXPOSE_CODES


async def build_user_out(session: AsyncSession, user: User) -> UserOut:
    profile_completed, diagnostic_skipped = await profiles_service.get_onboarding_flags(
        session, user.id
    )
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.display_name,
        phone=user.phone,
        role=user.role,
        email_verified=user.email_verified,
        onboarding=OnboardingOut(
            profile_completed=profile_completed,
            diagnostic_completed=await quizzes_service.has_completed_diagnostic(session, user.id),
            diagnostic_skipped=diagnostic_skipped,
        ),
    )


def _apply_token_claims(user: User, claims: dict[str, Any]) -> None:
    """Copy what Firebase knows: e.g. Google sign-in users arrive with email_verified=true."""
    if claims.get("email_verified") and not user.email_verified:
        user.email_verified = True
    user.last_login_at = clock.now()


# =========================================================================== account


async def register(
    session: AsyncSession, claims: dict[str, Any], req: RegisterRequest
) -> tuple[UserOut, bool]:
    """Create (or update) the users row for this Firebase account. Returns (user, created)."""
    if not req.consent:
        raise AppError("Please accept the terms and privacy policy", code="CONSENT_REQUIRED")
    phone = normalize_phone(req.phone)
    email = normalize_email(claims.get("email"))

    user = await repository.get_user_by_uid(session, claims["uid"])
    created = user is None
    if user is None:
        if email and await repository.get_user_by_email(session, email):
            raise ConflictError("This email belongs to another account", code="EMAIL_IN_USE")
        user = User(firebase_uid=claims["uid"], email=email, consent_at=clock.now())
        session.add(user)
    elif not user.is_active:
        raise ForbiddenError("This account is disabled", code="USER_DISABLED")

    user.display_name = req.full_name.strip()
    if req.phone is not None:
        user.phone = phone
    _apply_token_claims(user, claims)
    await session.commit()
    return await build_user_out(session, user), created


async def _get_registered_user(session: AsyncSession, claims: dict[str, Any]) -> User:
    user = await repository.get_user_by_uid(session, claims["uid"])
    if user is None:
        raise NotFoundError(
            "No account yet. Call POST /api/v1/auth/register first.", code="USER_NOT_FOUND"
        )
    if not user.is_active:
        raise ForbiddenError("This account is disabled", code="USER_DISABLED")
    return user


async def get_me(session: AsyncSession, claims: dict[str, Any]) -> UserOut:
    user = await _get_registered_user(session, claims)
    _apply_token_claims(user, claims)
    await session.commit()
    return await build_user_out(session, user)


async def update_me(session: AsyncSession, claims: dict[str, Any], req: UpdateMeRequest) -> UserOut:
    user = await _get_registered_user(session, claims)
    if "full_name" in req.model_fields_set and req.full_name is not None:
        user.display_name = req.full_name.strip()
    if "phone" in req.model_fields_set:
        user.phone = normalize_phone(req.phone)  # null / "" removes the phone
    await session.commit()
    return await build_user_out(session, user)


async def delete_me(session: AsyncSession, claims: dict[str, Any]) -> None:
    """DELETE /auth/me: remove ALL of the student's data, then the Firebase login.

    1. Each module deletes its own rows through its service (no commit yet) and tells us
       which Storage files / folders belong to the student.
    2. The users row (+ codes, reset tokens) is deleted.
    3. The Firebase login is deleted. If that fails, the database changes are rolled back,
       so nothing is lost and the student can simply try again.
    4. Commit, then delete the Storage files (answer photos, uploads, post images). Files
       are deleted last because that can't be undone; a failure is logged, never shown.
    """
    user = await repository.get_user_by_uid(session, claims["uid"])
    if user is None:  # no row (e.g. never registered): only the Firebase login is left
        await firebase_users.delete_user(claims["uid"])
        return

    storage_paths: list[str] = []
    for module_service in USER_DATA_SERVICES:
        storage_paths += await module_service.delete_user_data(session, user.id)
    await repository.delete_user(session, user)
    await session.flush()

    try:
        await firebase_users.delete_user(claims["uid"])
    except Exception:
        await session.rollback()
        raise
    await session.commit()

    failed = await run_in_threadpool(storage.delete_files, storage_paths)
    if failed:
        logger.error("Account %s deleted, but %s Storage path(s) were not", user.id, failed)


async def export_me(session: AsyncSession, claims: dict[str, Any]) -> dict[str, Any]:
    """GET /auth/me/export: a copy of everything we store about the CURRENT student.

    Only the caller's own rows are read (every service is asked for the caller's id).
    Works for a suspended account too (like GET /auth/me). Files are
    listed as Storage paths, never their bytes. No secrets: no Firebase uid, no codes, no
    reset tokens, no push (FCM) tokens.
    """
    user = await _get_registered_user(session, claims)  # 404 USER_NOT_FOUND before register
    profile_data = await profiles_service.export_user_data(session, user.id)
    attempts = await exams_service.export_user_data(session, user.id)
    plans = await recommendations_service.export_user_data(session, user.id)
    content = await content_service.export_user_data(session, user.id)
    privacy = {
        **profile_data["privacy"],
        "terms_accepted_at": user.consent_at,
        "push_devices": await notifications_service.count_devices(session, user.id),
    }
    return {
        "exported_at": clock.now().isoformat(),
        "account": {
            "id": user.id,
            "email": user.email,
            "full_name": user.display_name,
            "phone": user.phone,
            "role": user.role,
            "email_verified": user.email_verified,
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
        },
        "profile": profile_data["profile"],
        "settings": profile_data["settings"],
        "privacy": privacy,
        "achievements": profile_data["achievements"],
        "quiz_attempts": attempts["quiz_attempts"],
        "exam_attempts": attempts["exam_attempts"],
        "evaluations": await evaluation_service.export_user_data(session, user.id),
        "mistakes": await performance_service.export_user_data(session, user.id),
        "recommendations": plans["recommendations"],
        "study_plan": plans["study_plan"],
        "notes": content["notes"],
        "uploads": content["uploads"],
        "bookmarks": await learn_service.export_user_data(session, user.id),
        "community": await community_service.export_user_data(session, user.id),
        "notifications": await notifications_service.export_user_data(session, user.id),
    }


# =========================================================================== 6-digit codes


async def _create_and_send_code(
    session: AsyncSession,
    sender: EmailSender,
    *,
    email: str,
    purpose: str,
    user: User | None,
) -> CodeSentOut:
    """Cooldown check -> cancel older codes -> store the hash -> email the code."""
    now = clock.now()
    latest = await repository.latest_code(session, email, purpose)
    if latest is not None:
        waited = (now - latest.created_at).total_seconds()
        if waited < RESEND_COOLDOWN_SECONDS:
            retry_after = math.ceil(RESEND_COOLDOWN_SECONDS - waited)
            raise TooManyRequestsError(
                f"Please wait {retry_after} seconds before asking for a new code",
                code="RESEND_TOO_SOON",
                extra={"retry_after": retry_after},
            )

    code = new_code()
    await repository.close_open_codes(session, email, purpose, now)
    session.add(
        EmailCode(
            user_id=user.id if user else None,
            email=email,
            purpose=purpose,
            code_hash=hash_secret(purpose, code),
            expires_at=now + timedelta(seconds=CODE_TTL_SECONDS),
            created_at=now,
        )
    )
    await session.flush()  # saved in this transaction, but not committed yet

    # Send BEFORE committing: if the email fails, nothing is saved, the older code stays
    # valid and there is no 60-second cooldown - the student can tap "Resend" at once.
    if user is not None:  # unknown emails get no email, but the response looks the same
        try:
            await sender.send(build_code_email(email, code, purpose, CODE_TTL_SECONDS // 60))
        except AppError:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            logger.error("Sending the code email failed: %s", type(exc).__name__)
            raise ServiceUnavailableError(
                "We could not send the email right now. Please try again in a moment.",
                code="EMAIL_SEND_FAILED",
            ) from exc
    await session.commit()
    return CodeSentOut(
        resend_in=RESEND_COOLDOWN_SECONDS,
        expires_in=CODE_TTL_SECONDS,
        dev_code=code if dev_code_allowed() else None,
    )


async def _check_code(session: AsyncSession, *, email: str, purpose: str, code: str) -> EmailCode:
    """Return the matching code row (marked used) or raise the right error."""
    row = await repository.latest_code(session, email, purpose)
    now = clock.now()
    if row is None or row.consumed_at is not None:
        raise AppError("That code is not valid. Ask for a new one.", code="CODE_INVALID")
    if row.expires_at <= now:
        raise AppError("That code has expired. Ask for a new one.", code="CODE_EXPIRED")
    if row.attempts >= MAX_WRONG_ATTEMPTS:
        raise TooManyRequestsError(
            "Too many wrong tries. Ask for a new code.", code="TOO_MANY_ATTEMPTS"
        )
    if not hmac.compare_digest(row.code_hash, hash_secret(purpose, code)):
        row.attempts += 1
        await session.commit()
        raise AppError(
            "That code is not right. Check the email and try again.",
            code="CODE_INVALID",
            extra={"attempts_left": max(0, MAX_WRONG_ATTEMPTS - row.attempts)},
        )
    row.consumed_at = now
    return row


async def send_email_code(session: AsyncSession, user_id: Any, sender: EmailSender) -> CodeSentOut:
    user = await repository.get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError("Account not found", code="USER_NOT_FOUND")
    if user.email_verified:
        raise ConflictError("Your email is already verified", code="ALREADY_VERIFIED")
    if not user.email:
        raise AppError("This account has no email address", code="NO_EMAIL")
    return await _create_and_send_code(
        session, sender, email=user.email.lower(), purpose=VERIFY_EMAIL, user=user
    )


async def verify_email_code(session: AsyncSession, user_id: Any, code: str) -> UserOut:
    user = await repository.get_user_by_id(session, user_id)
    if user is None or not user.email:
        raise NotFoundError("Account not found", code="USER_NOT_FOUND")
    await _check_code(session, email=user.email.lower(), purpose=VERIFY_EMAIL, code=code)
    user.email_verified = True
    await session.commit()
    # Keep Firebase in sync so the app's next ID token also says email_verified=true.
    try:
        await firebase_users.update_user(user.firebase_uid, email_verified=True)
    except AppError:
        logger.warning("Email verified in our DB, but Firebase was not updated (user %s)", user.id)
    return await build_user_out(session, user)


# =========================================================================== password reset


async def send_reset_code(session: AsyncSession, email: str, sender: EmailSender) -> CodeSentOut:
    """Always "sent" - even for unknown emails - so nobody can probe which emails exist."""
    email = email.strip().lower()
    user = await repository.get_user_by_email(session, email)
    if user is not None and not user.is_active:
        user = None  # disabled accounts can't reset, but the response looks the same
    return await _create_and_send_code(
        session, sender, email=email, purpose=RESET_PASSWORD, user=user
    )


async def verify_reset_code(session: AsyncSession, email: str, code: str) -> ResetTokenOut:
    email = email.strip().lower()
    row = await _check_code(session, email=email, purpose=RESET_PASSWORD, code=code)
    if row.user_id is None:  # code for an unknown email (only reachable with dev_code)
        await session.commit()
        raise AppError("That code is not valid. Ask for a new one.", code="CODE_INVALID")

    token = secrets.token_urlsafe(32)  # 256 random bits, only its hash is stored
    now = clock.now()
    await repository.close_reset_tokens(session, row.user_id, now)
    session.add(
        PasswordResetToken(
            user_id=row.user_id,
            token_hash=hash_secret("reset_token", token),
            expires_at=now + timedelta(seconds=RESET_TOKEN_TTL_SECONDS),
        )
    )
    await session.commit()
    return ResetTokenOut(reset_token=token, expires_in=RESET_TOKEN_TTL_SECONDS)


async def complete_reset(session: AsyncSession, reset_token: str, new_password: str) -> None:
    token = await repository.get_reset_token(session, hash_secret("reset_token", reset_token))
    now = clock.now()
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise AppError(
            "This reset link has expired. Start again from 'Forgot password'.",
            code="RESET_TOKEN_INVALID",
        )
    check_password_policy(new_password)  # before using the token, so the user can retry
    user = await repository.get_user_by_id(session, token.user_id)
    if user is None:
        raise AppError("Account not found", code="RESET_TOKEN_INVALID")

    await firebase_users.update_user(user.firebase_uid, password=new_password)
    token.used_at = now
    await session.commit()


# =========================================================================== admin: Students
# Used by admin/users_admin.py.

INACTIVE_AFTER_DAYS = 30


def _inactive_before() -> date:
    return clock.today() - timedelta(days=INACTIVE_AFTER_DAYS)


def _student_out(row: repository.StudentRow, mastery: dict[Any, int]) -> AdminStudentOut:
    user = row.user
    return AdminStudentOut(
        id=user.id,
        full_name=(user.display_name or "").strip() or (user.email or "Student"),
        email=user.email,
        school=row.school,
        district=row.district,
        exam_year=row.exam_year,
        avg_mastery=mastery.get(user.id),
        status=row.status,  # type: ignore[arg-type]
        last_active_at=row.last_active_at,
    )


async def admin_list_students(
    session: AsyncSession,
    *,
    search: str | None,
    exam_year: int | None,
    status: str | None,
    district: str | None,
    offset: int,
    limit: int,
) -> AdminStudentPage:
    """Students only. inactive = no study activity for 30+ days; suspended wins over inactive."""
    rows, total, active_total = await repository.list_students(
        session,
        inactive_before=_inactive_before(),
        search=search,
        exam_year=exam_year,
        district=district,
        status=status,
        offset=offset,
        limit=limit,
    )
    mastery = await performance_service.average_mastery(session, [r.user.id for r in rows])
    return AdminStudentPage(
        items=[_student_out(r, mastery) for r in rows], total=total, active_total=active_total
    )


async def admin_set_active(
    session: AsyncSession, admin_id: Any, user_id: Any, is_active: bool
) -> AdminStudentOut:
    """Suspend (false) or reinstate (true). The Firebase account is disabled / enabled too, so a
    suspended student gets USER_DISABLED on every request and cannot sign in again."""
    user = await repository.get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError("User not found", code="USER_NOT_FOUND")
    if user.id == admin_id and not is_active:
        raise AppError("You cannot suspend your own account", code="CANNOT_SUSPEND_SELF")
    if user.is_active != is_active:
        # Firebase first: if it fails, nothing is changed in our database.
        await firebase_users.set_disabled(user.firebase_uid, disabled=not is_active)
        user.is_active = is_active
        user.disabled_at = None if is_active else clock.now()
        await session.commit()
    row = await repository.get_student_row(session, user.id, _inactive_before())
    assert row is not None
    mastery = await performance_service.average_mastery(session, [user.id])
    return _student_out(row, mastery)
