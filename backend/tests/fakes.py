"""In-memory stand-ins for the AWS adapters.

``FakeCognitoClient`` satisfies ``app.core.cognito.CognitoClient`` structurally and raises the
same ``AppError``s the boto3 implementation would, so use cases and routers are exercised end to
end without AWS. Tokens are ``access-<sub>`` / ``refresh-<sub>`` so tests can assert on them.
``FakeMailClient`` records every ``Mail`` instead of sending it.
"""

from dataclasses import dataclass, field
from uuid import uuid4

from app.core.cognito import CognitoTokens
from app.core.exceptions import AppError
from app.core.mail import Mail


@dataclass
class FakeCognitoUser:
    sub: str
    password: str | None = None
    full_name: str | None = None


@dataclass
class FakeCognitoClient:
    users: dict[str, FakeCognitoUser] = field(default_factory=dict)
    # Access tokens revoked through GlobalSignOut, and emails revoked through AdminUserGlobalSignOut.
    signed_out: list[str] = field(default_factory=list)
    admin_signed_out: list[str] = field(default_factory=list)

    def seed(self, email: str, password: str, *, full_name: str | None = None) -> FakeCognitoUser:
        """Pre-register a confirmed user, as if they had signed up earlier."""
        user = FakeCognitoUser(sub=str(uuid4()), password=password, full_name=full_name)
        self.users[email] = user
        return user

    async def create_user(self, email: str, *, full_name: str | None) -> str:
        if email in self.users:
            raise AppError.conflict("An account with this email already exists", cognito_code="UsernameExistsException")
        user = FakeCognitoUser(sub=str(uuid4()), full_name=full_name)
        self.users[email] = user
        return user.sub

    async def set_permanent_password(self, email: str, password: str) -> None:
        self._get(email).password = password

    async def delete_user(self, email: str) -> None:
        self._get(email)
        del self.users[email]

    async def password_auth(self, email: str, password: str) -> CognitoTokens:
        user = self.users.get(email)
        if user is None or user.password != password:
            raise AppError.auth_failed("Invalid email or password", cognito_code="NotAuthorizedException")
        return self._tokens(user.sub)

    async def refresh(self, refresh_token: str) -> CognitoTokens:
        prefix = "refresh-"
        if not refresh_token.startswith(prefix):
            raise AppError.auth_failed("Invalid or expired refresh token", cognito_code="NotAuthorizedException")
        return self._tokens(refresh_token.removeprefix(prefix))

    async def global_sign_out(self, access_token: str) -> None:
        if not access_token.startswith("access-"):
            raise AppError.auth_failed("Invalid or expired access token", cognito_code="NotAuthorizedException")
        self.signed_out.append(access_token)

    async def admin_global_sign_out(self, email: str) -> None:
        self._get(email)
        self.admin_signed_out.append(email)

    def _get(self, email: str) -> FakeCognitoUser:
        user = self.users.get(email)
        if user is None:
            raise AppError.auth_failed("User does not exist", cognito_code="UserNotFoundException")
        return user

    @staticmethod
    def _tokens(sub: str) -> CognitoTokens:
        return CognitoTokens(access_token=f"access-{sub}", refresh_token=f"refresh-{sub}", expires_in=3600)


@dataclass
class FakeMailClient:
    sent: list[Mail] = field(default_factory=list)

    async def send(self, mail: Mail) -> None:
        self.sent.append(mail)
