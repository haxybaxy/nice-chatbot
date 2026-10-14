"""HTTP tests for /api/organizations."""

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.models import OrganizationMemberModel, OrganizationModel, OrganizationRole
from app.users.models import UserModel
from tests.seeds import seed_member, seed_organization, seed_user

type Authenticate = Callable[[UserModel], None]


async def _members(db: AsyncSession, organization_id: UUID) -> dict[UUID, str]:
    result = await db.execute(
        select(OrganizationMemberModel).where(OrganizationMemberModel.organization_id == organization_id)
    )
    return {member.user_id: member.role for member in result.scalars()}


@pytest.fixture
async def owner(db_session: AsyncSession) -> UserModel:
    return await seed_user(db_session, email="owner@example.com", full_name="Org Owner")


@pytest.fixture
async def organization(db_session: AsyncSession, owner: UserModel) -> OrganizationModel:
    return await seed_organization(db_session, name="Acme", owner=owner)


class TestCreateOrganization:
    async def test_creator_becomes_owner(
        self, client: AsyncClient, db_session: AsyncSession, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.post("/api/organizations", json={"name": "Acme"})

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "Acme"
        assert await _members(db_session, UUID(body["id"])) == {owner.id: "owner"}

    async def test_requires_auth(self, client: AsyncClient) -> None:
        assert (await client.post("/api/organizations", json={"name": "Acme"})).status_code == 401


class TestGetOrganization:
    async def test_member_can_read(
        self, client: AsyncClient, organization: OrganizationModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.get(f"/api/organizations/{organization.id}")

        assert response.status_code == 200
        assert response.json()["id"] == str(organization.id)

    async def test_non_member_gets_404(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        authenticate_as: Authenticate,
    ) -> None:
        outsider = await seed_user(db_session, email="outsider@example.com")
        authenticate_as(outsider)

        assert (await client.get(f"/api/organizations/{organization.id}")).status_code == 404


class TestListMembers:
    async def test_lists_members_with_user_details(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        authenticate_as: Authenticate,
    ) -> None:
        member = await seed_user(db_session, email="member@example.com", full_name="A Member")
        await seed_member(db_session, organization, member, OrganizationRole.MEMBER)
        authenticate_as(member)

        response = await client.get(f"/api/organizations/{organization.id}/members")

        assert response.status_code == 200
        rows = {(row["user"]["email"], row["role"], row["user"]["fullName"]) for row in response.json()}
        assert rows == {("owner@example.com", "owner", "Org Owner"), ("member@example.com", "member", "A Member")}


class TestInviteMember:
    async def test_owner_adds_an_existing_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        invitee = await seed_user(db_session, email="invitee@example.com")
        authenticate_as(owner)

        response = await client.post(f"/api/organizations/{organization.id}/members", json={"email": invitee.email})

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["userId"] == str(invitee.id)
        assert body["role"] == "member"
        assert body["user"]["email"] == invitee.email
        assert await _members(db_session, organization.id) == {owner.id: "owner", invitee.id: "member"}

    async def test_member_cannot_invite(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        authenticate_as: Authenticate,
    ) -> None:
        member = await seed_user(db_session, email="member@example.com")
        await seed_member(db_session, organization, member, OrganizationRole.MEMBER)
        authenticate_as(member)

        response = await client.post(
            f"/api/organizations/{organization.id}/members", json={"email": "anyone@example.com"}
        )

        assert response.status_code == 403

    async def test_unknown_email_is_404(
        self, client: AsyncClient, organization: OrganizationModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.post(
            f"/api/organizations/{organization.id}/members", json={"email": "ghost@example.com"}
        )

        assert response.status_code == 404

    async def test_existing_member_is_409(
        self, client: AsyncClient, organization: OrganizationModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.post(f"/api/organizations/{organization.id}/members", json={"email": owner.email})

        assert response.status_code == 409

    async def test_admin_cannot_grant_admin(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        authenticate_as: Authenticate,
    ) -> None:
        admin = await seed_user(db_session, email="admin@example.com")
        await seed_member(db_session, organization, admin, OrganizationRole.ADMIN)
        invitee = await seed_user(db_session, email="invitee@example.com")
        authenticate_as(admin)

        response = await client.post(
            f"/api/organizations/{organization.id}/members", json={"email": invitee.email, "role": "admin"}
        )

        assert response.status_code == 403

    async def test_owner_role_is_not_grantable(
        self, client: AsyncClient, organization: OrganizationModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.post(
            f"/api/organizations/{organization.id}/members", json={"email": "x@example.com", "role": "owner"}
        )

        assert response.status_code == 422


class TestRemoveMember:
    async def test_owner_removes_a_member(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        member = await seed_user(db_session, email="member@example.com")
        await seed_member(db_session, organization, member, OrganizationRole.MEMBER)
        authenticate_as(owner)

        response = await client.delete(f"/api/organizations/{organization.id}/members/{member.id}")

        assert response.status_code == 204
        assert await _members(db_session, organization.id) == {owner.id: "owner"}

    async def test_owner_cannot_be_removed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        admin = await seed_user(db_session, email="admin@example.com")
        await seed_member(db_session, organization, admin, OrganizationRole.ADMIN)
        authenticate_as(admin)

        response = await client.delete(f"/api/organizations/{organization.id}/members/{owner.id}")

        assert response.status_code == 403
        assert (await _members(db_session, organization.id))[owner.id] == "owner"

    async def test_admin_cannot_remove_an_admin(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        authenticate_as: Authenticate,
    ) -> None:
        admin = await seed_user(db_session, email="admin@example.com")
        other_admin = await seed_user(db_session, email="admin2@example.com")
        await seed_member(db_session, organization, admin, OrganizationRole.ADMIN)
        await seed_member(db_session, organization, other_admin, OrganizationRole.ADMIN)
        authenticate_as(admin)

        response = await client.delete(f"/api/organizations/{organization.id}/members/{other_admin.id}")

        assert response.status_code == 403

    async def test_unknown_member_is_404(
        self, client: AsyncClient, organization: OrganizationModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(owner)

        response = await client.delete(f"/api/organizations/{organization.id}/members/{uuid4()}")

        assert response.status_code == 404
