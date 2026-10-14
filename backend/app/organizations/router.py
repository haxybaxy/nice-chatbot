"""Organization and membership routes. Every ``{organization_id}`` route is membership-gated."""

from collections.abc import Sequence
from uuid import UUID

from fastapi import APIRouter, status

from app.core.openapi import error_responses
from app.core.security import CurrentUserDep
from app.organizations.dependencies import (
    CreateOrganizationDep,
    GetOrganizationDep,
    InviteMemberDep,
    ListMembersDep,
    ManagerDep,
    MembershipDep,
    RemoveMemberDep,
)
from app.organizations.models import OrganizationMemberModel, OrganizationModel
from app.organizations.schemas import CreateOrganizationIn, InviteMemberIn, OrganizationMemberOut, OrganizationOut

router = APIRouter(prefix="/organizations", tags=["organizations"], responses=error_responses(401))


@router.post(
    "",
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization",
    responses=error_responses(422),
)
async def create_organization(
    body: CreateOrganizationIn, current_user: CurrentUserDep, use_case: CreateOrganizationDep
) -> OrganizationModel:
    """The caller becomes the organization's owner."""
    return await use_case.execute(name=body.name, creator=current_user)


@router.get(
    "/{organization_id}",
    response_model=OrganizationOut,
    summary="Get an organization",
    responses=error_responses(404, 422),
)
async def get_organization(membership: MembershipDep, use_case: GetOrganizationDep) -> OrganizationModel:
    return await use_case.execute(organization_id=membership.organization_id)


@router.get(
    "/{organization_id}/members",
    response_model=list[OrganizationMemberOut],
    summary="List members",
    responses=error_responses(404, 422),
)
async def list_members(membership: MembershipDep, use_case: ListMembersDep) -> Sequence[OrganizationMemberModel]:
    return await use_case.execute(organization_id=membership.organization_id)


@router.post(
    "/{organization_id}/members",
    response_model=OrganizationMemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member",
    responses=error_responses(403, 404, 409, 422),
)
async def invite_member(body: InviteMemberIn, actor: ManagerDep, use_case: InviteMemberDep) -> OrganizationMemberModel:
    """Adds an existing user by email. Owners and admins may add members; only the owner may grant admin."""
    return await use_case.execute(actor=actor, email=body.email, role=body.role)


@router.delete(
    "/{organization_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member",
    responses=error_responses(403, 404, 422),
)
async def remove_member(user_id: UUID, actor: ManagerDep, use_case: RemoveMemberDep) -> None:
    """The owner cannot be removed; only the owner may remove an admin."""
    await use_case.execute(actor=actor, user_id=user_id)
