"""HTTP endpoints for the auth module. Owner: Mogith.

"token" = Firebase ID token in `Authorization: Bearer <token>`.

    POST   /api/v1/auth/register                 token   create/update my users row (201 new / 200)
    GET    /api/v1/auth/me                       token   my account + onboarding flags
    PATCH  /api/v1/auth/me                       token   change full_name / phone
    DELETE /api/v1/auth/me                       token   delete my account (DB + Firebase)
    POST   /api/v1/auth/email-code/send          token   email a 6-digit verification code
    POST   /api/v1/auth/email-code/verify        token   check it -> email_verified = true
    POST   /api/v1/auth/password-reset/send      none    email a 6-digit reset code (always 200)
    POST   /api/v1/auth/password-reset/verify    none    check it -> reset_token
    POST   /api/v1/auth/password-reset/complete  none    reset_token + new password

Rule: routers only validate input, check the role and call `service`. No SQL here.
"""

from fastapi import APIRouter, Response, status

from api.core.database import SessionDep
from api.core.email import EmailSenderDep
from api.core.security import CurrentUserDep, FirebaseClaimsDep
from api.modules.auth import service
from api.modules.auth.schemas import (
    CodeSentOut,
    ModuleStatus,
    PasswordResetCompleteRequest,
    PasswordResetSendRequest,
    PasswordResetVerifyRequest,
    RegisterRequest,
    ResetDoneOut,
    ResetTokenOut,
    UpdateMeRequest,
    UserOut,
    VerifyCodeRequest,
)

router = APIRouter(tags=["Auth"])


@router.get("/auth/status", response_model=ModuleStatus, summary="Placeholder: module status")
async def module_status(user: CurrentUserDep) -> ModuleStatus:
    """Placeholder route. Needs a logged-in user."""
    return await service.get_status()


# ---------------------------------------------------------------- account


@router.post(
    "/auth/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create my account row after Firebase sign-up (201), or update it (200)",
)
async def register(
    req: RegisterRequest, claims: FirebaseClaimsDep, session: SessionDep, response: Response
) -> UserOut:
    user, created = await service.register(session, claims, req)
    if not created:
        response.status_code = status.HTTP_200_OK
    return user


@router.get("/auth/me", response_model=UserOut, summary="My account and onboarding progress")
async def get_me(claims: FirebaseClaimsDep, session: SessionDep) -> UserOut:
    return await service.get_me(session, claims)


@router.patch("/auth/me", response_model=UserOut, summary="Change my name or phone")
async def update_me(
    req: UpdateMeRequest, claims: FirebaseClaimsDep, session: SessionDep
) -> UserOut:
    return await service.update_me(session, claims, req)


@router.delete(
    "/auth/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete my account (all data + the Firebase login)",
)
async def delete_me(claims: FirebaseClaimsDep, session: SessionDep) -> Response:
    await service.delete_me(session, claims)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- email verification


@router.post(
    "/auth/email-code/send",
    response_model=CodeSentOut,
    response_model_exclude_none=True,
    summary="Email me a 6-digit verification code",
)
async def send_email_code(
    user: CurrentUserDep, session: SessionDep, sender: EmailSenderDep
) -> CodeSentOut:
    return await service.send_email_code(session, user.id, sender)


@router.post(
    "/auth/email-code/verify", response_model=UserOut, summary="Verify my email with the code"
)
async def verify_email_code(
    req: VerifyCodeRequest, user: CurrentUserDep, session: SessionDep
) -> UserOut:
    return await service.verify_email_code(session, user.id, req.code)


# ---------------------------------------------------------------- password reset (no login)


@router.post(
    "/auth/password-reset/send",
    response_model=CodeSentOut,
    response_model_exclude_none=True,
    summary="Email a 6-digit reset code (always answers 'sent')",
)
async def send_reset_code(
    req: PasswordResetSendRequest, session: SessionDep, sender: EmailSenderDep
) -> CodeSentOut:
    return await service.send_reset_code(session, req.email, sender)


@router.post(
    "/auth/password-reset/verify",
    response_model=ResetTokenOut,
    summary="Check the reset code and get a short-lived reset_token",
)
async def verify_reset_code(req: PasswordResetVerifyRequest, session: SessionDep) -> ResetTokenOut:
    return await service.verify_reset_code(session, req.email, req.code)


@router.post(
    "/auth/password-reset/complete",
    response_model=ResetDoneOut,
    summary="Set a new password with the reset_token",
)
async def complete_reset(req: PasswordResetCompleteRequest, session: SessionDep) -> ResetDoneOut:
    await service.complete_reset(session, req.reset_token, req.new_password)
    return ResetDoneOut()
