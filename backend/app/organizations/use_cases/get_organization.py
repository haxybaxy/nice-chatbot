from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.organizations.models import OrganizationModel
from app.organizations.repository import OrganizationRepository


class GetOrganization:
    def __init__(self, session: AsyncSession) -> None:
        self._organizations = OrganizationRepository(session)

    async def execute(self, *, organization_id: UUID) -> OrganizationModel:
        organization = await self._organizations.get_by_id(organization_id)
        if organization is None:
            raise AppError.not_found("Organization", organization_id)
        return organization
