"""Sign-up / sign-in / refresh / sign-out and password reset, proxied to AWS Cognito (the reset
mail goes out through SES).

Handlers return the use case's result as-is; ``response_model`` builds the ``*Out`` schema
from it exactly once.
"""

from fastapi import APIRouter, status

from app.auth.dependencies import (
    RefreshSessionDep,
    RequestPasswordResetDep,
    ResetPasswordDep,
    SignInDep,
    SignOutDep,
    SignUpDep,
)
from app.auth.schemas import ForgotPasswordIn, RefreshIn, ResetPasswordIn, SignInIn, SignUpIn, SignUpOut, TokensOut
from app.auth.use_cases.sign_up import AuthSession
from app.core.cognito import CognitoTokens
from app.core.openapi import error_responses
from app.core.security import AccessTokenDep

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=SignUpOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses=error_responses(400, 409, 422),
)
async def sign_up(body: SignUpIn, use_case: SignUpDep) -> AuthSession:
    """Creates the Cognito user, the local account with its personal organization and default team, then signs in."""
    return await use_case.execute(email=body.email, password=body.password, full_name=body.full_name)


@router.post(
    "/signin",
    response_model=TokensOut,
    summary="Sign in with email and password",
    responses=error_responses(401, 422),
)
async def sign_in(body: SignInIn, use_case: SignInDep) -> CognitoTokens:
    return await use_case.execute(email=body.email, password=body.password)


@router.post(
    "/refresh",
    response_model=TokensOut,
    summary="Exchange a refresh token for new tokens",
    responses=error_responses(401, 422),
)
async def refresh(body: RefreshIn, use_case: RefreshSessionDep) -> CognitoTokens:
    return await use_case.execute(refresh_token=body.refresh_token)


@router.post(
    "/signout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out of every session",
    responses=error_responses(401),
)
async def sign_out(access_token: AccessTokenDep, use_case: SignOutDep) -> None:
    """Revokes all of the caller's refresh tokens. Existing access tokens stay valid until expiry."""
    await use_case.execute(access_token=access_token)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Email a password-reset link",
    responses=error_responses(422),
)
async def forgot_password(body: ForgotPasswordIn, use_case: RequestPasswordResetDep) -> None:
    """Always 204, whether or not an account exists, so addresses cannot be enumerated.

    The mailed link works once and expires after 30 minutes; a new request replaces it.
    """
    await use_case.execute(email=body.email)


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password with a reset link's token",
    responses=error_responses(400, 422),
)
async def reset_password(body: ResetPasswordIn, use_case: ResetPasswordDep) -> None:
    """Sets the password and revokes every session of the user.

    400 for an unknown, expired or already used token, or a password the pool's policy rejects.
    """
    await use_case.execute(token=body.token, password=body.password)
