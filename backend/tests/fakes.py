"""In-memory stand-ins for the AWS adapters.

``FakeCognitoClient`` satisfies ``app.core.cognito.CognitoClient`` structurally and raises the
same ``AppError``s the boto3 implementation would, so use cases and routers are exercised end to
end without AWS. Tokens are ``access-<sub>`` / ``refresh-<sub>`` so tests can assert on them.
``FakeMailClient`` records every ``Mail`` instead of sending it. ``FakeListener`` replaces the
Postgres ``LISTEN``/``NOTIFY`` connection: NOTIFY is invisible inside the rolled-back test
transaction, so tests call ``notify`` themselves after writing rows.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from app.core.cognito import CognitoTokens
from app.core.exceptions import AppError
from app.core.mail import Mail
from app.db.listen import ANY_KEY, wait_for_event


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


class _ObservedEvent(asyncio.Event):
    """An event that flags ``waiting`` when a subscriber blocks on it — the moment a test may
    write rows and notify without racing the subscriber's own database reads."""

    def __init__(self, waiting: asyncio.Event) -> None:
        super().__init__()
        self._waiting = waiting

    async def wait(self) -> Literal[True]:
        self._waiting.set()
        return await super().wait()


@dataclass
class FakeListener:
    """In-memory ``app.db.listen.Listener``: same waiter keys, no connection."""

    subscriptions: dict[tuple[str, str], set[asyncio.Event]] = field(default_factory=dict)
    # Set whenever a subscriber starts waiting; clear it to observe the next wait.
    waiting: asyncio.Event = field(default_factory=asyncio.Event)
    notified: list[tuple[str, str]] = field(default_factory=list)

    @asynccontextmanager
    async def subscribe(self, channel: str, key: str = ANY_KEY) -> AsyncGenerator[asyncio.Event]:
        event = _ObservedEvent(self.waiting)
        waiters = self.subscriptions.setdefault((channel, key), set())
        waiters.add(event)
        try:
            yield event
        finally:
            waiters.discard(event)

    async def wait(self, channel: str, key: str = ANY_KEY, *, timeout_s: float) -> bool:
        async with self.subscribe(channel, key) as event:
            return await wait_for_event(event, timeout_s)

    def notify(self, channel: str, payload: str) -> None:
        """What ``pg_notify(channel, payload)`` would do once the writer committed."""
        self.notified.append((channel, payload))
        key = payload.split(":", 1)[0]
        for waiter_key in ((channel, key), (channel, ANY_KEY)):
            for event in self.subscriptions.get(waiter_key, ()):
                event.set()
