from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.organizations.use_cases.find_membership import FindMembership
from app.teams.models import TeamMemberModel
from app.teams.repository import TeamMemberRepository


class RemoveTeamMember:
    """Remove a member from a team. Anyone may leave; removing someone else takes the team
    creator or an organization owner/admin (``TeamModel.is_managed_by``)."""

    def __init__(self, session: AsyncSession) -> None:
        self._find_membership = FindMembership(session)
        self._members = TeamMemberRepository(session)

    async def execute(self, *, actor: TeamMemberModel, user_id: UUID) -> None:
        team = actor.team
        if user_id != actor.user_id:
            organization_member = await self._find_membership.execute(
                organization_id=team.organization_id, user_id=actor.user_id
            )
            if not team.is_managed_by(actor.user_id, organization_member):
                raise AppError.forbidden("Only the team creator or an organization owner/admin can remove members")
        member = await self._members.get(team.id, user_id)
        if member is None:
            raise AppError.not_found("Member", user_id)
        await self._members.delete(member)
