"""HTTP tests for /api/users/me."""

from collections.abc import Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import UserModel
from tests.fakes import FakeCognitoClient
from tests.seeds import seed_user

EMAIL = "me@example.com"


class TestMe:
    async def test_get_returns_the_profile(
        self, client: AsyncClient, db_session: AsyncSession, authenticate_as: Callable[[UserModel], None]
    ) -> None:
        user = await seed_user(db_session, email=EMAIL, full_name="Me Myself")
        authenticate_as(user)

        response = await client.get("/api/users/me")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(user.id)
        assert body["email"] == EMAIL
        assert body["fullName"] == "Me Myself"
        assert body["createdAt"].endswith("Z")

    async def test_get_without_auth_is_401(self, client: AsyncClient) -> None:
        assert (await client.get("/api/users/me")).status_code == 401

    async def test_patch_updates_the_name(
        self, client: AsyncClient, db_session: AsyncSession, authenticate_as: Callable[[UserModel], None]
    ) -> None:
        user = await seed_user(db_session, email=EMAIL)
        authenticate_as(user)

        response = await client.patch("/api/users/me", json={"fullName": "Renamed"})

        assert response.status_code == 200
        assert response.json()["fullName"] == "Renamed"
        await db_session.refresh(user)
        assert user.full_name == "Renamed"

    async def test_delete_removes_local_row_and_cognito_identity(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        cognito: FakeCognitoClient,
        authenticate_as: Callable[[UserModel], None],
    ) -> None:
        identity = cognito.seed(EMAIL, "StrongPass1!")
        user = await seed_user(db_session, email=EMAIL, cognito_sub=identity.sub)
        authenticate_as(user)

        response = await client.delete("/api/users/me")

        assert response.status_code == 204
        assert await db_session.get(UserModel, user.id) is None
        assert EMAIL not in cognito.users
