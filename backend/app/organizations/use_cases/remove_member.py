from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.organizations.models import OrganizationMemberModel, OrganizationRole
from app.organizations.repository import OrganizationMemberRepository


class RemoveMember:
    """Remove a member from the actor's organization.

    Rules: owners and admins can remove; the owner can never be removed; only the owner can
    remove an admin.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._members = OrganizationMemberRepository(session)

    async def execute(self, *, actor: OrganizationMemberModel, user_id: UUID) -> None:
        member = await self._members.get(actor.organization_id, user_id)
        if member is None:
            raise AppError.not_found("Member", user_id)
        if member.has_role(OrganizationRole.OWNER):
            raise AppError.forbidden("The owner cannot be removed")
        if member.has_role(OrganizationRole.ADMIN) and not actor.has_role(OrganizationRole.OWNER):
            raise AppError.forbidden("Only the owner can remove an admin")
        await self._members.delete(member)
