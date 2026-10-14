"""Team and team-membership routes. Every ``{team_id}`` route is membership-gated; creating a
team hangs off the organization it belongs to."""

from collections.abc import Sequence
from uuid import UUID

from fastapi import APIRouter, status

from app.core.openapi import error_responses
from app.core.security import CurrentUserDep
from app.teams.dependencies import (
    AddTeamMemberDep,
    CreateTeamInOrganizationDep,
    GetTeamDep,
    ListMyTeamsDep,
    ListTeamMembersDep,
    OrganizationMembershipDep,
    RemoveTeamMemberDep,
    TeamManagerDep,
    TeamMembershipDep,
)
from app.teams.models import TeamMemberModel, TeamModel
from app.teams.schemas import AddTeamMemberIn, CreateTeamIn, TeamMemberOut, TeamOut

router = APIRouter(tags=["teams"], responses=error_responses(401))


@router.get("/teams", response_model=list[TeamOut], summary="List my teams")
async def list_my_teams(current_user: CurrentUserDep, use_case: ListMyTeamsDep) -> Sequence[TeamModel]:
    """The teams the caller is a member of, across all their organizations."""
    return await use_case.execute(user_id=current_user.id)


@router.post(
    "/organizations/{organization_id}/teams",
    response_model=TeamOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a team",
    responses=error_responses(404, 409, 422),
)
async def create_team(
    body: CreateTeamIn,
    membership: OrganizationMembershipDep,
    current_user: CurrentUserDep,
    use_case: CreateTeamInOrganizationDep,
) -> TeamModel:
    """Any organization member may create a team; the creator becomes its first member."""
    return await use_case.execute(membership=membership, name=body.name, creator=current_user)


@router.get("/teams/{team_id}", response_model=TeamOut, summary="Get a team", responses=error_responses(404, 422))
async def get_team(membership: TeamMembershipDep, use_case: GetTeamDep) -> TeamModel:
    return await use_case.execute(team_id=membership.team_id)


@router.get(
    "/teams/{team_id}/members",
    response_model=list[TeamMemberOut],
    summary="List team members",
    responses=error_responses(404, 422),
)
async def list_team_members(membership: TeamMembershipDep, use_case: ListTeamMembersDep) -> Sequence[TeamMemberModel]:
    return await use_case.execute(team_id=membership.team_id)


@router.post(
    "/teams/{team_id}/members",
    response_model=TeamMemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a team member",
    responses=error_responses(403, 404, 409, 422),
)
async def add_team_member(
    body: AddTeamMemberIn, manager: TeamManagerDep, use_case: AddTeamMemberDep
) -> TeamMemberModel:
    """Adds an organization member by email. The team creator and organization owners/admins may add."""
    return await use_case.execute(team=manager.team, email=body.email)


@router.delete(
    "/teams/{team_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a team member",
    responses=error_responses(403, 404, 422),
)
async def remove_team_member(user_id: UUID, membership: TeamMembershipDep, use_case: RemoveTeamMemberDep) -> None:
    """Anyone may remove themselves; removing others takes the team creator or an organization owner/admin."""
    await use_case.execute(actor=membership, user_id=user_id)
