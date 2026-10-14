"""Data access for organizations and memberships. Flushes, never commits."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.models import OrganizationMemberModel, OrganizationModel


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, organization: OrganizationModel) -> OrganizationModel:
        self._session.add(organization)
        await self._session.flush()
        await self._session.refresh(organization)
        return organization

    async def get_by_id(self, organization_id: UUID) -> OrganizationModel | None:
        return await self._session.get(OrganizationModel, organization_id)


class OrganizationMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, member: OrganizationMemberModel) -> OrganizationMemberModel:
        self._session.add(member)
        await self._session.flush()
        await self._session.refresh(member)
        return member

    async def get(self, organization_id: UUID, user_id: UUID) -> OrganizationMemberModel | None:
        result = await self._session.execute(
            select(OrganizationMemberModel).where(
                OrganizationMemberModel.organization_id == organization_id,
                OrganizationMemberModel.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_organization(self, organization_id: UUID) -> Sequence[OrganizationMemberModel]:
        result = await self._session.execute(
            select(OrganizationMemberModel)
            .where(OrganizationMemberModel.organization_id == organization_id)
            .order_by(OrganizationMemberModel.created_at, OrganizationMemberModel.id)
        )
        return result.scalars().all()

    async def delete(self, member: OrganizationMemberModel) -> None:
        await self._session.delete(member)
        await self._session.flush()
