"""HTTP tests for /api/teams and /api/organizations/{organization_id}/teams."""

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.models import OrganizationModel, OrganizationRole
from app.teams.models import TeamMemberModel, TeamModel
from app.users.models import UserModel
from tests.seeds import seed_member, seed_organization, seed_team, seed_team_member, seed_user

type Authenticate = Callable[[UserModel], None]


async def _member_ids(db: AsyncSession, team_id: UUID) -> set[UUID]:
    result = await db.execute(select(TeamMemberModel.user_id).where(TeamMemberModel.team_id == team_id))
    return set(result.scalars())


@pytest.fixture
async def owner(db_session: AsyncSession) -> UserModel:
    return await seed_user(db_session, email="owner@example.com", full_name="Org Owner")


@pytest.fixture
async def organization(db_session: AsyncSession, owner: UserModel) -> OrganizationModel:
    return await seed_organization(db_session, name="Nice Chatbot", owner=owner)


@pytest.fixture
async def creator(db_session: AsyncSession, organization: OrganizationModel) -> UserModel:
    """A plain organization member who created the team."""
    user = await seed_user(db_session, email="creator@example.com", full_name="Team Creator")
    await seed_member(db_session, organization, user, OrganizationRole.MEMBER)
    return user


@pytest.fixture
async def team(db_session: AsyncSession, organization: OrganizationModel, creator: UserModel) -> TeamModel:
    return await seed_team(db_session, organization=organization, name="Research", creator=creator)


@pytest.fixture
async def member(db_session: AsyncSession, organization: OrganizationModel, team: TeamModel) -> UserModel:
    """An organization member who is also in the team, without any management right."""
    user = await seed_user(db_session, email="member@example.com", full_name="Team Member")
    await seed_member(db_session, organization, user, OrganizationRole.MEMBER)
    await seed_team_member(db_session, team, user)
    return user


class TestListMyTeams:
    async def test_lists_only_the_callers_teams(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        owner: UserModel,
        creator: UserModel,
        team: TeamModel,
        authenticate_as: Authenticate,
    ) -> None:
        other_org = await seed_organization(db_session, name="Elsewhere", owner=owner)
        await seed_team(db_session, organization=other_org, name="Owner only", creator=owner)
        await seed_team(db_session, organization=organization, name="Also mine", creator=creator)
        authenticate_as(creator)

        response = await client.get("/api/teams")

        assert response.status_code == 200, response.text
        body = response.json()
        assert [row["name"] for row in body] == ["Research", "Also mine"]
        assert body[0]["id"] == str(team.id)
        assert body[0]["organization"] == {"id": str(organization.id), "name": "Nice Chatbot"}
        assert body[0]["createdBy"] == str(creator.id)

    async def test_requires_auth(self, client: AsyncClient) -> None:
        assert (await client.get("/api/teams")).status_code == 401


class TestCreateTeam:
    async def test_member_creates_a_team_and_joins_it(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        creator: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(creator)

        response = await client.post(f"/api/organizations/{organization.id}/teams", json={"name": "Design"})

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "Design"
        assert body["organizationId"] == str(organization.id)
        assert body["organization"]["name"] == "Nice Chatbot"
        assert await _member_ids(db_session, UUID(body["id"])) == {creator.id}

    async def test_non_member_gets_404(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        authenticate_as: Authenticate,
    ) -> None:
        outsider = await seed_user(db_session, email="outsider@example.com")
        authenticate_as(outsider)

        response = await client.post(f"/api/organizations/{organization.id}/teams", json={"name": "Design"})

        assert response.status_code == 404

    async def test_duplicate_name_is_409(
        self,
        client: AsyncClient,
        organization: OrganizationModel,
        team: TeamModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(owner)

        response = await client.post(f"/api/organizations/{organization.id}/teams", json={"name": team.name})

        assert response.status_code == 409


class TestGetTeam:
    async def test_member_can_read(
        self, client: AsyncClient, team: TeamModel, member: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(member)

        response = await client.get(f"/api/teams/{team.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(team.id)
        assert body["organization"]["id"] == str(team.organization_id)

    async def test_organization_member_outside_the_team_gets_404(
        self, client: AsyncClient, team: TeamModel, owner: UserModel, authenticate_as: Authenticate
    ) -> None:
        """Even the organization owner is not in a team they did not join."""
        authenticate_as(owner)

        assert (await client.get(f"/api/teams/{team.id}")).status_code == 404


class TestListTeamMembers:
    async def test_lists_members_with_user_details(
        self, client: AsyncClient, team: TeamModel, member: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(member)

        response = await client.get(f"/api/teams/{team.id}/members")

        assert response.status_code == 200
        rows = {(row["user"]["email"], row["user"]["fullName"], row["teamId"]) for row in response.json()}
        assert rows == {
            ("creator@example.com", "Team Creator", str(team.id)),
            ("member@example.com", "Team Member", str(team.id)),
        }


class TestAddTeamMember:
    async def test_creator_adds_an_organization_member(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        team: TeamModel,
        creator: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        invitee = await seed_user(db_session, email="invitee@example.com")
        await seed_member(db_session, organization, invitee, OrganizationRole.MEMBER)
        authenticate_as(creator)

        response = await client.post(f"/api/teams/{team.id}/members", json={"email": invitee.email})

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["userId"] == str(invitee.id)
        assert body["user"]["email"] == invitee.email
        assert await _member_ids(db_session, team.id) == {creator.id, invitee.id}

    async def test_organization_owner_in_the_team_may_add(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        team: TeamModel,
        owner: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        await seed_team_member(db_session, team, owner)
        invitee = await seed_user(db_session, email="invitee@example.com")
        await seed_member(db_session, organization, invitee, OrganizationRole.MEMBER)
        authenticate_as(owner)

        response = await client.post(f"/api/teams/{team.id}/members", json={"email": invitee.email})

        assert response.status_code == 201, response.text

    async def test_plain_member_cannot_add(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        organization: OrganizationModel,
        team: TeamModel,
        member: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        invitee = await seed_user(db_session, email="invitee@example.com")
        await seed_member(db_session, organization, invitee, OrganizationRole.MEMBER)
        authenticate_as(member)

        response = await client.post(f"/api/teams/{team.id}/members", json={"email": invitee.email})

        assert response.status_code == 403
        assert invitee.id not in await _member_ids(db_session, team.id)

    async def test_unknown_email_and_non_organization_member_are_404(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        creator: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        outsider = await seed_user(db_session, email="outsider@example.com")
        authenticate_as(creator)

        for email in ("ghost@example.com", outsider.email):
            response = await client.post(f"/api/teams/{team.id}/members", json={"email": email})
            assert response.status_code == 404, email

    async def test_existing_member_is_409(
        self, client: AsyncClient, team: TeamModel, creator: UserModel, member: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(creator)

        response = await client.post(f"/api/teams/{team.id}/members", json={"email": member.email})

        assert response.status_code == 409


class TestRemoveTeamMember:
    async def test_creator_removes_a_member(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        creator: UserModel,
        member: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(creator)

        response = await client.delete(f"/api/teams/{team.id}/members/{member.id}")

        assert response.status_code == 204
        assert await _member_ids(db_session, team.id) == {creator.id}

    async def test_member_may_leave(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        creator: UserModel,
        member: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(member)

        response = await client.delete(f"/api/teams/{team.id}/members/{member.id}")

        assert response.status_code == 204
        assert await _member_ids(db_session, team.id) == {creator.id}

    async def test_member_cannot_remove_others(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        team: TeamModel,
        creator: UserModel,
        member: UserModel,
        authenticate_as: Authenticate,
    ) -> None:
        authenticate_as(member)

        response = await client.delete(f"/api/teams/{team.id}/members/{creator.id}")

        assert response.status_code == 403
        assert creator.id in await _member_ids(db_session, team.id)

    async def test_unknown_member_is_404(
        self, client: AsyncClient, team: TeamModel, creator: UserModel, authenticate_as: Authenticate
    ) -> None:
        authenticate_as(creator)

        assert (await client.delete(f"/api/teams/{team.id}/members/{uuid4()}")).status_code == 404
