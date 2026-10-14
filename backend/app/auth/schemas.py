"""HTTP schemas for the auth API."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.core.schemas import BaseSchema, BaseSchemaOut, NormalizedEmail, UtcDatetime, VerbatimStr


class SignUpIn(BaseSchema):
    email: NormalizedEmail
    # The pool's password policy is the real gate; this is just a floor before the round-trip.
    password: VerbatimStr = Field(min_length=8, max_length=256)
    full_name: str | None = Field(default=None, min_length=1, max_length=255)


class SignInIn(BaseSchema):
    email: NormalizedEmail
    password: VerbatimStr = Field(max_length=256)


class RefreshIn(BaseSchema):
    # A credential: verbatim, and bounded (Cognito refresh tokens are ~1-2 KB opaque strings).
    refresh_token: VerbatimStr = Field(max_length=8192)


class ForgotPasswordIn(BaseSchema):
    email: NormalizedEmail


class ResetPasswordIn(BaseSchema):
    # The raw token from the mailed link (43 characters today) — a credential, so verbatim.
    token: VerbatimStr = Field(min_length=1, max_length=128)
    # The pool's password policy is the real gate; this is just a floor before the round-trip.
    password: VerbatimStr = Field(min_length=8, max_length=256)


class TokensOut(BaseSchemaOut):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: Literal["bearer"] = "bearer"  # noqa: S105


class AuthUserOut(BaseSchemaOut):
    id: UUID
    email: str
    full_name: str | None = None
    created_at: UtcDatetime


class AuthOrganizationOut(BaseSchemaOut):
    id: UUID
    name: str


class AuthTeamOut(BaseSchemaOut):
    id: UUID
    name: str


class SignUpOut(BaseSchemaOut):
    """The new user, the personal organization and default team created with them, and a session."""

    user: AuthUserOut
    organization: AuthOrganizationOut
    team: AuthTeamOut
    tokens: TokensOut
