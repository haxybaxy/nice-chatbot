"""Data access for teams and team memberships. Flushes, never commits."""

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


class TeamMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, member: TeamMemberModel) -> TeamMemberModel:
        self._session.add(member)
        await self._session.flush()
        await self._session.refresh(member)
        return member
