"""Bearer-token authentication against the Cognito user pool.

Access tokens are verified locally against the pool's JWKS — RS256 signature, issuer, expiry,
``token_use == "access"`` and the app ``client_id`` — so there is no network round-trip per
request once the signing keys are cached. The token's ``sub`` is resolved to the local
``UserModel``; the local ``id`` is what the rest of the app works with.

``bearer_scheme`` is an ``HTTPBearer`` so the OpenAPI document carries a ``BearerAuth`` security
scheme and Swagger UI shows an Authorize button.
"""

import asyncio
from functools import cache
from typing import Annotated, ClassVar

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError
from pydantic import BaseModel, ConfigDict, ValidationError  # noqa: TID251

from app.core.config import cognito_settings
from app.core.context import bind_user_id
from app.core.exceptions import AppError
from app.core.logging_config import get_logger
from app.db.session import DbDep
from app.users.models import UserModel
from app.users.repository import UserRepository

logger = get_logger(__name__)

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    bearerFormat="JWT",
    description="Cognito access token from POST /api/auth/signin",
)


class AccessTokenClaims(BaseModel):
    """Typed view over the verified JWT payload (``jwt.decode`` returns an untyped dict).

    Not an HTTP boundary schema, so it stays on ``pydantic.BaseModel`` (exempt from ``TID251`` in
    pyproject): standard JWT claims would trip ``BaseSchema``'s ``extra="forbid"`` and camelCase
    aliasing does not apply to claim names.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    sub: str
    token_use: str
    client_id: str


@cache
def _jwks_client() -> PyJWKClient:
    # Lazily fetches and caches the pool's signing keys; no network I/O until the first token.
    return PyJWKClient(cognito_settings.jwks_url, cache_keys=True)


async def verify_access_token(token: str) -> AccessTokenClaims:
    """Verify a Cognito access token and return its claims, or raise 401 (503 if JWKS is down)."""
    try:
        # PyJWKClient fetches over urllib — blocking, hence the thread.
        signing_key = await asyncio.to_thread(_jwks_client().get_signing_key_from_jwt, token)
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=cognito_settings.issuer,
            # Access tokens carry `client_id`, not `aud`; it is checked below.
            options={"verify_aud": False, "require": ["exp", "iat", "sub"]},
        )
        claims = AccessTokenClaims.model_validate(payload)
    except PyJWKClientConnectionError as error:
        raise AppError.service_unavailable("Unable to fetch token signing keys", cause=error) from error
    except (jwt.PyJWTError, ValidationError) as error:
        logger.debug("token verification failed", error_type=type(error).__name__)
        raise AppError.auth_failed("Invalid or expired token") from error
    if claims.token_use != "access":  # noqa: S105
        raise AppError.auth_failed("Invalid or expired token", reason="token_use")
    if claims.client_id != cognito_settings.cognito_client_id:
        raise AppError.auth_failed("Invalid or expired token", reason="client_id")
    return claims


async def get_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    """The raw bearer token, or 401 when the header is missing or not a Bearer scheme."""
    if credentials is None:
        raise AppError.auth_failed("Authentication required")
    return credentials.credentials


async def get_current_user(token: Annotated[str, Depends(get_bearer_token)], db: DbDep) -> UserModel:
    claims = await verify_access_token(token)
    user = await UserRepository(db).get_by_cognito_sub(claims.sub)
    if user is None:
        logger.warning("no local user for cognito sub", cognito_sub=claims.sub)
        raise AppError.auth_failed("Unknown user")
    bind_user_id(str(user.id))
    return user


AccessTokenDep = Annotated[str, Depends(get_bearer_token)]
CurrentUserDep = Annotated[UserModel, Depends(get_current_user)]
