"""FastAPI dependencies for the teams domain.

``get_team_membership`` resolves ``{team_id}`` from the path and returns the caller's membership
(404 otherwise — a non-member can't tell whether the team exists); ``get_team_manager`` layers the
member-management rule on top (403). ``get_organization_membership`` resolves
``{organization_id}`` through the organizations domain's public use case, so this module never
imports ``organizations.dependencies``.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.core.exceptions import AppError
from app.core.security import CurrentUserDep
from app.db.session import DbDep
from app.organizations.models import OrganizationMemberModel
from app.organizations.use_cases.find_membership import FindMembership
from app.teams.models import TeamMemberModel
from app.teams.use_cases.add_team_member import AddTeamMember
from app.teams.use_cases.create_team_in_organization import CreateTeamInOrganization
from app.teams.use_cases.find_team_membership import FindTeamMembership
from app.teams.use_cases.get_team import GetTeam
from app.teams.use_cases.list_my_teams import ListMyTeams
from app.teams.use_cases.list_team_members import ListTeamMembers
from app.teams.use_cases.remove_team_member import RemoveTeamMember


async def get_team_membership(team_id: UUID, current_user: CurrentUserDep, db: DbDep) -> TeamMemberModel:
    membership = await FindTeamMembership(db).execute(team_id=team_id, user_id=current_user.id)
    if membership is None:
        raise AppError.not_found("Team", team_id)
    return membership


TeamMembershipDep = Annotated[TeamMemberModel, Depends(get_team_membership)]


async def get_team_manager(membership: TeamMembershipDep, db: DbDep) -> TeamMemberModel:
    """The caller's membership when they may manage the team's members: its creator, or an
    owner/admin of the organization."""
    team = membership.team
    organization_member = await FindMembership(db).execute(
        organization_id=team.organization_id, user_id=membership.user_id
    )
    if not team.is_managed_by(membership.user_id, organization_member):
        raise AppError.forbidden("Only the team creator or an organization owner/admin can manage members")
    return membership


TeamManagerDep = Annotated[TeamMemberModel, Depends(get_team_manager)]


async def get_organization_membership(
    organization_id: UUID, current_user: CurrentUserDep, db: DbDep
) -> OrganizationMemberModel:
    membership = await FindMembership(db).execute(organization_id=organization_id, user_id=current_user.id)
    if membership is None:
        raise AppError.not_found("Organization", organization_id)
    return membership


OrganizationMembershipDep = Annotated[OrganizationMemberModel, Depends(get_organization_membership)]


async def list_my_teams_use_case(db: DbDep) -> ListMyTeams:
    return ListMyTeams(db)


async def get_team_use_case(db: DbDep) -> GetTeam:
    return GetTeam(db)


async def create_team_in_organization_use_case(db: DbDep) -> CreateTeamInOrganization:
    return CreateTeamInOrganization(db)


async def list_team_members_use_case(db: DbDep) -> ListTeamMembers:
    return ListTeamMembers(db)


async def add_team_member_use_case(db: DbDep) -> AddTeamMember:
    return AddTeamMember(db)


async def remove_team_member_use_case(db: DbDep) -> RemoveTeamMember:
    return RemoveTeamMember(db)


ListMyTeamsDep = Annotated[ListMyTeams, Depends(list_my_teams_use_case)]
GetTeamDep = Annotated[GetTeam, Depends(get_team_use_case)]
CreateTeamInOrganizationDep = Annotated[CreateTeamInOrganization, Depends(create_team_in_organization_use_case)]
ListTeamMembersDep = Annotated[ListTeamMembers, Depends(list_team_members_use_case)]
AddTeamMemberDep = Annotated[AddTeamMember, Depends(add_team_member_use_case)]
RemoveTeamMemberDep = Annotated[RemoveTeamMember, Depends(remove_team_member_use_case)]
