"""FastAPI dependencies for the organizations domain.

``get_membership`` resolves ``{organization_id}`` from the path (the parameter name matches)
and returns the caller's membership; ``require_role`` layers a role check on top. Use-case
factories follow the ``<verb_noun>_use_case`` → ``<VerbNoun>Dep`` naming.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.core.exceptions import AppError
from app.core.security import CurrentUserDep
from app.db.session import DbDep
from app.organizations.models import OrganizationMemberModel, OrganizationRole
from app.organizations.repository import OrganizationMemberRepository
from app.organizations.use_cases.create_organization import CreateOrganization
from app.organizations.use_cases.get_organization import GetOrganization
from app.organizations.use_cases.invite_member import InviteMember
from app.organizations.use_cases.list_members import ListMembers
from app.organizations.use_cases.remove_member import RemoveMember


async def get_membership(organization_id: UUID, current_user: CurrentUserDep, db: DbDep) -> OrganizationMemberModel:
    """The caller's membership in the organization, or 404 — a non-member can't tell whether
    the organization exists."""
    member = await OrganizationMemberRepository(db).get(organization_id, current_user.id)
    if member is None:
        raise AppError.not_found("Organization", organization_id)
    return member


MembershipDep = Annotated[OrganizationMemberModel, Depends(get_membership)]


def require_role(*roles: OrganizationRole) -> Callable[..., Awaitable[OrganizationMemberModel]]:
    async def _check(membership: MembershipDep) -> OrganizationMemberModel:
        if not membership.has_role(*roles):
            raise AppError.forbidden("Insufficient role in this organization")
        return membership

    return _check


ManagerDep = Annotated[OrganizationMemberModel, Depends(require_role(OrganizationRole.OWNER, OrganizationRole.ADMIN))]


async def create_organization_use_case(db: DbDep) -> CreateOrganization:
    return CreateOrganization(db)


async def get_organization_use_case(db: DbDep) -> GetOrganization:
    return GetOrganization(db)


async def list_members_use_case(db: DbDep) -> ListMembers:
    return ListMembers(db)


async def invite_member_use_case(db: DbDep) -> InviteMember:
    return InviteMember(db)


async def remove_member_use_case(db: DbDep) -> RemoveMember:
    return RemoveMember(db)


CreateOrganizationDep = Annotated[CreateOrganization, Depends(create_organization_use_case)]
GetOrganizationDep = Annotated[GetOrganization, Depends(get_organization_use_case)]
ListMembersDep = Annotated[ListMembers, Depends(list_members_use_case)]
InviteMemberDep = Annotated[InviteMember, Depends(invite_member_use_case)]
RemoveMemberDep = Annotated[RemoveMember, Depends(remove_member_use_case)]
