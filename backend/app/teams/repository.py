"""Data access for teams and team memberships. Flushes, never commits."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.teams.models import TeamMemberModel, TeamModel


class TeamRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, team: TeamModel) -> TeamModel:
        self._session.add(team)
        await self._session.flush()
        await self._session.refresh(team)
        return team

    async def get_by_id(self, team_id: UUID) -> TeamModel | None:
        return await self._session.get(TeamModel, team_id)

    async def get_by_name(self, organization_id: UUID, name: str) -> TeamModel | None:
        result = await self._session.execute(
            select(TeamModel).where(TeamModel.organization_id == organization_id, TeamModel.name == name)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> Sequence[TeamModel]:
        result = await self._session.execute(
            select(TeamModel)
            .join(TeamMemberModel, TeamMemberModel.team_id == TeamModel.id)
            .where(TeamMemberModel.user_id == user_id)
            .order_by(TeamModel.created_at, TeamModel.id)
        )
        return result.scalars().all()


class TeamMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, member: TeamMemberModel) -> TeamMemberModel:
        self._session.add(member)
        await self._session.flush()
        await self._session.refresh(member)
        return member

    async def get(self, team_id: UUID, user_id: UUID) -> TeamMemberModel | None:
        result = await self._session.execute(
            select(TeamMemberModel).where(TeamMemberModel.team_id == team_id, TeamMemberModel.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_team(self, team_id: UUID) -> Sequence[TeamMemberModel]:
        result = await self._session.execute(
            select(TeamMemberModel)
            .where(TeamMemberModel.team_id == team_id)
            .order_by(TeamMemberModel.created_at, TeamMemberModel.id)
        )
        return result.scalars().all()

    async def delete(self, member: TeamMemberModel) -> None:
        await self._session.delete(member)
        await self._session.flush()
