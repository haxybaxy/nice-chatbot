"""AWS Cognito adapter — the identity-provider seam every auth flow goes through.

``CognitoClient`` is the Protocol the use cases depend on; ``Boto3CognitoClient`` is the real
implementation over ``cognito-idp``; tests inject an in-memory fake by overriding
``get_cognito_client``. boto3 is synchronous, so every call runs in a worker thread. botocore
``ClientError``s are translated to ``AppError`` here, so callers never see provider-specific
exceptions.

Supported setup: a PUBLIC app client (no secret) with ``ALLOW_ADMIN_USER_PASSWORD_AUTH`` and
``ALLOW_REFRESH_TOKEN_AUTH``. A client secret is honoured on the username-keyed calls, but
``REFRESH_TOKEN_AUTH`` cannot compute ``SECRET_HASH`` from a refresh token alone.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Annotated, Protocol

import boto3  # noqa: TID251
from botocore.exceptions import ClientError  # noqa: TID251
from fastapi import Depends

from app.core.config import aws_settings, cognito_settings
from app.core.exceptions import AppError
from app.core.logging_config import get_logger

if TYPE_CHECKING:
    from mypy_boto3_cognito_idp import CognitoIdentityProviderClient
    from mypy_boto3_cognito_idp.type_defs import AttributeTypeTypeDef, AuthenticationResultTypeTypeDef

logger = get_logger(__name__)

_THROTTLE_CODES = frozenset({"TooManyRequestsException", "LimitExceededException", "ThrottlingException"})


@dataclass(frozen=True, slots=True)
class CognitoTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class CognitoClient(Protocol):
    async def create_user(self, email: str, *, full_name: str | None) -> str:
        """Create a user with a verified email and no invite message; return its ``sub``."""
        ...

    async def set_permanent_password(self, email: str, password: str) -> None: ...

    async def delete_user(self, email: str) -> None: ...

    async def password_auth(self, email: str, password: str) -> CognitoTokens: ...

    async def refresh(self, refresh_token: str) -> CognitoTokens: ...

    async def global_sign_out(self, access_token: str) -> None:
        """Invalidate every session of the token's user (all refresh tokens)."""
        ...

    async def admin_global_sign_out(self, email: str) -> None:
        """Invalidate every session of ``email``'s user by admin authority (no user token needed)."""
        ...


# ── botocore error translation ────────────────────────────────────────────────


def _error_parts(error: ClientError) -> tuple[str, str]:
    info = error.response.get("Error")
    if info is None:
        return "", ""
    return info.get("Code", ""), info.get("Message", "")


def _translate(error: ClientError, *, not_authorized: str) -> AppError:
    """Map a cognito-idp ``ClientError`` to the ``AppError`` the client should see."""
    code, message = _error_parts(error)
    if code == "UsernameExistsException":
        return AppError.conflict("An account with this email already exists", cognito_code=code)
    if code in ("NotAuthorizedException", "UserNotFoundException"):
        return AppError.auth_failed(not_authorized, cognito_code=code)
    if code in ("InvalidPasswordException", "InvalidParameterException"):
        return AppError.bad_request(message or "Invalid request", cognito_code=code)
    if code in _THROTTLE_CODES:
        return AppError.service_unavailable(
            "Authentication service is busy, please retry", cause=error, cognito_code=code
        )
    return AppError.internal("Identity provider error", cause=error, cognito_code=code)


def _attribute(attributes: list[AttributeTypeTypeDef] | None, name: str) -> str | None:
    for attribute in attributes or []:
        if attribute.get("Name") == name:
            return attribute.get("Value")
    return None


def _tokens(result: AuthenticationResultTypeTypeDef | None, *, fallback_refresh_token: str = "") -> CognitoTokens:
    """Build tokens from an ``AuthenticationResult``.

    ``REFRESH_TOKEN_AUTH`` responses omit ``RefreshToken`` (the original stays valid), so the
    caller passes the incoming one as ``fallback_refresh_token``.
    """
    access_token = result.get("AccessToken") if result else None
    if not result or not access_token:
        raise AppError.internal("Identity provider returned no tokens")
    return CognitoTokens(
        access_token=access_token,
        refresh_token=result.get("RefreshToken") or fallback_refresh_token,
        expires_in=result.get("ExpiresIn") or 3600,
    )


# ── boto3 implementation ─────────────────────────────────────────────────────


class Boto3CognitoClient:
    """``CognitoClient`` over boto3 ``cognito-idp``."""

    def __init__(
        self,
        *,
        region: str,
        user_pool_id: str,
        client_id: str,
        client_secret: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
    ) -> None:
        # Credentials are optional: None → boto3's default chain (env vars, profile, IAM role).
        # boto3-stubs types `client` as one overload per AWS service; the ones whose stub
        # package isn't installed return Unknown, which strict mode flags on the member access
        # even though the cognito-idp overload we hit is fully typed.
        self._client: CognitoIdentityProviderClient = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "cognito-idp",
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )
        self._user_pool_id = user_pool_id
        self._client_id = client_id
        self._client_secret = client_secret

    def _with_secret_hash(self, params: dict[str, str], username: str) -> dict[str, str]:
        """Attach ``SECRET_HASH`` (HMAC-SHA256 of username + client id) for a confidential client."""
        if not self._client_secret:
            return params
        digest = hmac.new(
            self._client_secret.encode("utf-8"), (username + self._client_id).encode("utf-8"), hashlib.sha256
        ).digest()
        return {**params, "SECRET_HASH": base64.b64encode(digest).decode("utf-8")}

    async def create_user(self, email: str, *, full_name: str | None) -> str:
        attributes: list[AttributeTypeTypeDef] = [
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
        ]
        if full_name:
            attributes.append({"Name": "name", "Value": full_name})
        try:
            response = await asyncio.to_thread(
                self._client.admin_create_user,
                UserPoolId=self._user_pool_id,
                Username=email,
                MessageAction="SUPPRESS",
                UserAttributes=attributes,
            )
        except ClientError as error:
            raise _translate(error, not_authorized="Not authorized to create users") from error
        sub = _attribute(response["User"].get("Attributes"), "sub")
        if not sub:
            raise AppError.internal("Identity provider did not return a user id")
        logger.info("cognito user created", cognito_sub=sub)
        return sub

    async def set_permanent_password(self, email: str, password: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.admin_set_user_password,
                UserPoolId=self._user_pool_id,
                Username=email,
                Password=password,
                Permanent=True,
            )
        except ClientError as error:
            raise _translate(error, not_authorized="Not authorized to set passwords") from error

    async def delete_user(self, email: str) -> None:
        try:
            await asyncio.to_thread(self._client.admin_delete_user, UserPoolId=self._user_pool_id, Username=email)
        except ClientError as error:
            raise _translate(error, not_authorized="Not authorized to delete users") from error

    async def password_auth(self, email: str, password: str) -> CognitoTokens:
        try:
            response = await asyncio.to_thread(
                self._client.admin_initiate_auth,
                UserPoolId=self._user_pool_id,
                ClientId=self._client_id,
                AuthFlow="ADMIN_USER_PASSWORD_AUTH",
                AuthParameters=self._with_secret_hash({"USERNAME": email, "PASSWORD": password}, email),
            )
        except ClientError as error:
            raise _translate(error, not_authorized="Invalid email or password") from error
        challenge = response.get("ChallengeName")
        if challenge:
            # MFA / forced password change are not part of this scaffold.
            raise AppError.auth_failed(f"Unsupported authentication challenge: {challenge}", challenge=challenge)
        return _tokens(response.get("AuthenticationResult"))

    async def refresh(self, refresh_token: str) -> CognitoTokens:
        try:
            response = await asyncio.to_thread(
                self._client.admin_initiate_auth,
                UserPoolId=self._user_pool_id,
                ClientId=self._client_id,
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={"REFRESH_TOKEN": refresh_token},
            )
        except ClientError as error:
            raise _translate(error, not_authorized="Invalid or expired refresh token") from error
        return _tokens(response.get("AuthenticationResult"), fallback_refresh_token=refresh_token)

    async def global_sign_out(self, access_token: str) -> None:
        try:
            await asyncio.to_thread(self._client.global_sign_out, AccessToken=access_token)
        except ClientError as error:
            raise _translate(error, not_authorized="Invalid or expired access token") from error

    async def admin_global_sign_out(self, email: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.admin_user_global_sign_out, UserPoolId=self._user_pool_id, Username=email
            )
        except ClientError as error:
            raise _translate(error, not_authorized="Not authorized to revoke sessions") from error


# ── FastAPI wiring ───────────────────────────────────────────────────────────


@cache
def _default_client() -> Boto3CognitoClient:
    # Built on first use, not at import: tests override the dependency and never touch boto3.
    secret = aws_settings.aws_secret_access_key
    client_secret = cognito_settings.cognito_client_secret
    return Boto3CognitoClient(
        region=cognito_settings.aws_region,
        user_pool_id=cognito_settings.cognito_user_pool_id,
        client_id=cognito_settings.cognito_client_id,
        client_secret=client_secret.get_secret_value() if client_secret else None,
        access_key_id=aws_settings.aws_access_key_id,
        secret_access_key=secret.get_secret_value() if secret else None,
    )


async def get_cognito_client() -> CognitoClient:
    return _default_client()


CognitoDep = Annotated[CognitoClient, Depends(get_cognito_client)]
