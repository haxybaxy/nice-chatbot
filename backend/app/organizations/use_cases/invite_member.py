from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.organizations.models import OrganizationMemberModel, OrganizationRole
from app.organizations.repository import OrganizationMemberRepository
from app.users.use_cases.find_user_by_email import FindUserByEmail


class InviteMember:
    """Add an existing user (looked up by email) to the actor's organization.

    No invitation email is sent — there is no email infrastructure yet; the user must already
    have an account. Rules: owners and admins can invite; only the owner can grant ``admin``;
    ``owner`` is never grantable.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._find_user = FindUserByEmail(session)
        self._members = OrganizationMemberRepository(session)

    async def execute(
        self, *, actor: OrganizationMemberModel, email: str, role: OrganizationRole
    ) -> OrganizationMemberModel:
        if role is OrganizationRole.OWNER:
            raise AppError.forbidden("The owner role cannot be granted")
        if role is OrganizationRole.ADMIN and not actor.has_role(OrganizationRole.OWNER):
            raise AppError.forbidden("Only the owner can grant the admin role")
        user = await self._find_user.execute(email=email)
        if user is None:
            raise AppError.not_found("User", email)
        if await self._members.get(actor.organization_id, user.id) is not None:
            raise AppError.conflict("User is already a member of this organization")
        return await self._members.add(
            OrganizationMemberModel(
                organization_id=actor.organization_id,
                user_id=user.id,
                role=role.value,
                user=user,
            )
        )
