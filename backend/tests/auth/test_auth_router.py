"""HTTP tests for /api/auth, with Cognito and SES replaced by the in-memory fakes."""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import PasswordResetTokenModel
from app.core.cognito import CognitoTokens
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.mail import Mail
from app.organizations.models import OrganizationMemberModel, OrganizationModel
from app.teams.models import TeamMemberModel, TeamModel
from app.users.models import UserModel
from tests.fakes import FakeCognitoClient, FakeMailClient
from tests.seeds import seed_password_reset_token, seed_user

EMAIL = "new@example.com"
PASSWORD = "StrongPass1!"
NEW_PASSWORD = "EvenStronger2!"
RESET_URL_PREFIX = f"{settings.frontend_url}/auth/reset-password?token="
_TOKEN_IN_URL = re.compile(r"[?&]token=([A-Za-z0-9_-]+)")


async def _local_user(db: AsyncSession, email: str) -> UserModel | None:
    return (await db.execute(select(UserModel).where(UserModel.email == email))).scalar_one_or_none()


def _mailed_token(mail: Mail) -> str:
    match = _TOKEN_IN_URL.search(mail.text)
    assert match is not None, mail.text
    return match.group(1)


async def _reset_tokens(db: AsyncSession, user_id: UUID) -> list[PasswordResetTokenModel]:
    result = await db.execute(select(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == user_id))
    return list(result.scalars())


class TestSignUp:
    async def test_creates_cognito_identity_and_local_user(
        self, client: AsyncClient, db_session: AsyncSession, cognito: FakeCognitoClient
    ) -> None:
        response = await client.post(
            "/api/auth/signup", json={"email": EMAIL, "password": PASSWORD, "fullName": "New User"}
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["user"]["email"] == EMAIL
        assert body["user"]["fullName"] == "New User"
        assert body["tokens"]["accessToken"].startswith("access-")
        local = await _local_user(db_session, EMAIL)
        assert local is not None
        assert local.cognito_sub == cognito.users[EMAIL].sub
        assert cognito.users[EMAIL].password == PASSWORD

    async def test_creates_a_personal_organization_and_a_default_team(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        response = await client.post(
            "/api/auth/signup", json={"email": EMAIL, "password": PASSWORD, "fullName": "New User"}
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["organization"]["name"] == "New User's organization"
        assert body["team"]["name"] == "General"
        user = await _local_user(db_session, EMAIL)
        assert user is not None
        organization = await db_session.get(OrganizationModel, UUID(body["organization"]["id"]))
        assert organization is not None
        assert organization.created_by == user.id
        memberships = await db_session.execute(
            select(OrganizationMemberModel).where(OrganizationMemberModel.organization_id == organization.id)
        )
        assert {member.user_id: member.role for member in memberships.scalars()} == {user.id: "owner"}
        team = await db_session.get(TeamModel, UUID(body["team"]["id"]))
        assert team is not None
        assert team.organization_id == organization.id
        assert team.created_by == user.id
        team_members = await db_session.execute(select(TeamMemberModel).where(TeamMemberModel.team_id == team.id))
        assert [member.user_id for member in team_members.scalars()] == [user.id]

    @pytest.mark.parametrize(
        ("full_name", "organization_name"),
        [
            pytest.param(None, "new's organization", id="falls back to the email local part"),
            pytest.param("x" * 255, "x" * 240 + "'s organization", id="keeps the suffix when the name is long"),
        ],
    )
    async def test_organization_is_named_after_the_user(
        self, client: AsyncClient, full_name: str | None, organization_name: str
    ) -> None:
        response = await client.post(
            "/api/auth/signup", json={"email": EMAIL, "password": PASSWORD, "fullName": full_name}
        )

        assert response.status_code == 201, response.text
        assert response.json()["organization"]["name"] == organization_name

    async def test_failure_after_the_rows_are_written_leaves_nothing_behind(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        cognito: FakeCognitoClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _cognito_down(_email: str, _password: str) -> CognitoTokens:
            raise AppError.service_unavailable("Authentication service is busy, please retry")

        # The closing sign-in runs after the user, organization and team rows are written.
        monkeypatch.setattr(cognito, "password_auth", _cognito_down)

        response = await client.post(
            "/api/auth/signup", json={"email": EMAIL, "password": PASSWORD, "fullName": "New User"}
        )

        assert response.status_code == 503
        assert await _local_user(db_session, EMAIL) is None
        assert (await db_session.execute(select(func.count()).select_from(OrganizationModel))).scalar_one() == 0
        assert (await db_session.execute(select(func.count()).select_from(TeamModel))).scalar_one() == 0
        assert EMAIL not in cognito.users

    async def test_trims_inputs_but_keeps_the_password_verbatim(
        self, client: AsyncClient, db_session: AsyncSession, cognito: FakeCognitoClient
    ) -> None:
        padded_password = f"  {PASSWORD} "
        response = await client.post(
            "/api/auth/signup",
            json={"email": "  New@Example.COM ", "password": padded_password, "fullName": "  New User "},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["user"]["email"] == EMAIL
        assert body["user"]["fullName"] == "New User"
        assert await _local_user(db_session, EMAIL) is not None
        # A password with surrounding whitespace is still that password: it must reach Cognito untouched.
        assert cognito.users[EMAIL].password == padded_password

    async def test_existing_cognito_user_is_409_and_creates_nothing(
        self, client: AsyncClient, db_session: AsyncSession, cognito: FakeCognitoClient
    ) -> None:
        cognito.seed(EMAIL, PASSWORD)

        response = await client.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})

        assert response.status_code == 409
        assert await _local_user(db_session, EMAIL) is None

    async def test_existing_local_user_rolls_back_the_cognito_identity(
        self, client: AsyncClient, db_session: AsyncSession, cognito: FakeCognitoClient
    ) -> None:
        await seed_user(db_session, email=EMAIL)

        response = await client.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})

        assert response.status_code == 409
        assert EMAIL not in cognito.users


class TestSignIn:
    async def test_returns_tokens(self, client: AsyncClient, cognito: FakeCognitoClient) -> None:
        cognito.seed(EMAIL, PASSWORD)

        response = await client.post("/api/auth/signin", json={"email": EMAIL, "password": PASSWORD})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["tokenType"] == "bearer"
        assert body["accessToken"] == f"access-{cognito.users[EMAIL].sub}"
        assert body["refreshToken"] == f"refresh-{cognito.users[EMAIL].sub}"

    async def test_wrong_password_is_401(self, client: AsyncClient, cognito: FakeCognitoClient) -> None:
        cognito.seed(EMAIL, PASSWORD)

        response = await client.post("/api/auth/signin", json={"email": EMAIL, "password": "wrong"})

        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_FAILED"


class TestRefresh:
    async def test_exchanges_a_refresh_token(self, client: AsyncClient) -> None:
        response = await client.post("/api/auth/refresh", json={"refreshToken": "refresh-abc"})

        assert response.status_code == 200
        assert response.json()["accessToken"] == "access-abc"

    async def test_invalid_refresh_token_is_401(self, client: AsyncClient) -> None:
        response = await client.post("/api/auth/refresh", json={"refreshToken": "garbage"})

        assert response.status_code == 401


class TestSignOut:
    async def test_revokes_the_callers_sessions(self, client: AsyncClient, cognito: FakeCognitoClient) -> None:
        response = await client.post("/api/auth/signout", headers={"Authorization": "Bearer access-xyz"})

        assert response.status_code == 204
        assert cognito.signed_out == ["access-xyz"]

    async def test_without_bearer_is_401(self, client: AsyncClient) -> None:
        assert (await client.post("/api/auth/signout")).status_code == 401


class TestForgotPassword:
    async def test_mails_a_reset_link_and_stores_only_its_hash(
        self, client: AsyncClient, db_session: AsyncSession, mail: FakeMailClient
    ) -> None:
        user = await seed_user(db_session, email=EMAIL)

        response = await client.post("/api/auth/forgot-password", json={"email": EMAIL})

        assert response.status_code == 204, response.text
        (sent,) = mail.sent
        assert sent.to == EMAIL
        assert sent.subject == "Reset your Acme password"
        assert RESET_URL_PREFIX in sent.text
        assert RESET_URL_PREFIX in sent.html
        raw_token = _mailed_token(sent)
        (token,) = await _reset_tokens(db_session, user.id)
        assert token.token_hash == PasswordResetTokenModel.hash_token(raw_token)
        assert raw_token not in token.token_hash
        assert timedelta(minutes=29) < token.expires_at - datetime.now(UTC) <= timedelta(minutes=30)

    async def test_unknown_email_is_204_and_sends_nothing(
        self, client: AsyncClient, db_session: AsyncSession, mail: FakeMailClient
    ) -> None:
        response = await client.post("/api/auth/forgot-password", json={"email": EMAIL})

        assert response.status_code == 204
        assert mail.sent == []
        count = await db_session.execute(select(func.count()).select_from(PasswordResetTokenModel))
        assert count.scalar_one() == 0

    async def test_replaces_the_previous_link(
        self, client: AsyncClient, db_session: AsyncSession, mail: FakeMailClient
    ) -> None:
        user = await seed_user(db_session, email=EMAIL)
        await seed_password_reset_token(db_session, user=user, raw_token="old-link")

        response = await client.post("/api/auth/forgot-password", json={"email": EMAIL})

        assert response.status_code == 204
        (token,) = await _reset_tokens(db_session, user.id)
        assert token.token_hash == PasswordResetTokenModel.hash_token(_mailed_token(mail.sent[0]))
        assert token.token_hash != PasswordResetTokenModel.hash_token("old-link")

    async def test_failed_send_leaves_no_link_behind(
        self, client: AsyncClient, db_session: AsyncSession, mail: FakeMailClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user = await seed_user(db_session, email=EMAIL)

        async def _ses_down(_mail: Mail) -> None:
            raise AppError.service_unavailable("Email service is busy, please retry")

        monkeypatch.setattr(mail, "send", _ses_down)

        response = await client.post("/api/auth/forgot-password", json={"email": EMAIL})

        assert response.status_code == 503
        assert await _reset_tokens(db_session, user.id) == []


class TestResetPassword:
    async def test_sets_the_password_revokes_sessions_and_consumes_the_link(
        self, client: AsyncClient, db_session: AsyncSession, cognito: FakeCognitoClient
    ) -> None:
        identity = cognito.seed(EMAIL, PASSWORD)
        user = await seed_user(db_session, email=EMAIL, cognito_sub=identity.sub)
        await seed_password_reset_token(db_session, user=user, raw_token="fresh-link")
        body = {"token": "fresh-link", "password": NEW_PASSWORD}

        response = await client.post("/api/auth/reset-password", json=body)

        assert response.status_code == 204, response.text
        assert cognito.users[EMAIL].password == NEW_PASSWORD
        assert cognito.admin_signed_out == [EMAIL]
        assert await _reset_tokens(db_session, user.id) == []
        # The link is single-use.
        assert (await client.post("/api/auth/reset-password", json=body)).status_code == 400

    async def test_end_to_end_from_the_mailed_link(
        self, client: AsyncClient, db_session: AsyncSession, cognito: FakeCognitoClient, mail: FakeMailClient
    ) -> None:
        identity = cognito.seed(EMAIL, PASSWORD)
        await seed_user(db_session, email=EMAIL, cognito_sub=identity.sub)
        assert (await client.post("/api/auth/forgot-password", json={"email": EMAIL})).status_code == 204

        response = await client.post(
            "/api/auth/reset-password", json={"token": _mailed_token(mail.sent[0]), "password": NEW_PASSWORD}
        )

        assert response.status_code == 204, response.text
        signin = await client.post("/api/auth/signin", json={"email": EMAIL, "password": NEW_PASSWORD})
        assert signin.status_code == 200, signin.text

    async def test_unknown_token_is_400(self, client: AsyncClient) -> None:
        response = await client.post("/api/auth/reset-password", json={"token": "nope", "password": NEW_PASSWORD})

        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "BAD_REQUEST"
        assert body["error"] == "Invalid or expired reset link"

    async def test_expired_link_is_400(
        self, client: AsyncClient, db_session: AsyncSession, cognito: FakeCognitoClient
    ) -> None:
        identity = cognito.seed(EMAIL, PASSWORD)
        user = await seed_user(db_session, email=EMAIL, cognito_sub=identity.sub)
        await seed_password_reset_token(db_session, user=user, raw_token="stale-link", expires_in=timedelta(minutes=-1))

        response = await client.post("/api/auth/reset-password", json={"token": "stale-link", "password": NEW_PASSWORD})

        assert response.status_code == 400
        assert cognito.users[EMAIL].password == PASSWORD

    async def test_rejected_password_keeps_the_link_usable(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        cognito: FakeCognitoClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        identity = cognito.seed(EMAIL, PASSWORD)
        user = await seed_user(db_session, email=EMAIL, cognito_sub=identity.sub)
        await seed_password_reset_token(db_session, user=user, raw_token="fresh-link")

        async def _policy_rejection(_email: str, _password: str) -> None:
            raise AppError.bad_request("Password does not conform to policy", cognito_code="InvalidPasswordException")

        monkeypatch.setattr(cognito, "set_permanent_password", _policy_rejection)

        response = await client.post("/api/auth/reset-password", json={"token": "fresh-link", "password": "weakweak"})

        assert response.status_code == 400
        assert len(await _reset_tokens(db_session, user.id)) == 1
        assert cognito.admin_signed_out == []

    async def test_session_revocation_is_best_effort(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        cognito: FakeCognitoClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        identity = cognito.seed(EMAIL, PASSWORD)
        user = await seed_user(db_session, email=EMAIL, cognito_sub=identity.sub)
        await seed_password_reset_token(db_session, user=user, raw_token="fresh-link")

        async def _cognito_down(_email: str) -> None:
            raise AppError.service_unavailable("Authentication service is busy, please retry")

        monkeypatch.setattr(cognito, "admin_global_sign_out", _cognito_down)

        response = await client.post("/api/auth/reset-password", json={"token": "fresh-link", "password": NEW_PASSWORD})

        assert response.status_code == 204, response.text
        assert cognito.users[EMAIL].password == NEW_PASSWORD
        assert await _reset_tokens(db_session, user.id) == []
