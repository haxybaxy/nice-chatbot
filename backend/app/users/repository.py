"""Data access for the ``user`` table. Flushes, never commits — ``get_db`` owns the transaction."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import UserModel


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: UserModel) -> UserModel:
        self._session.add(user)
        return await self.save(user)

    async def save(self, user: UserModel) -> UserModel:
        """Flush pending changes and reload server-side defaults (timestamps)."""
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def get_by_id(self, user_id: UUID) -> UserModel | None:
        return await self._session.get(UserModel, user_id)

    async def get_by_email(self, email: str) -> UserModel | None:
        # Emails are normalized to lowercase on write; compare case-insensitively anyway so a
        # mixed-case lookup still resolves to the one row.
        result = await self._session.execute(select(UserModel).where(func.lower(UserModel.email) == email.lower()))
        return result.scalar_one_or_none()

    async def get_by_cognito_sub(self, cognito_sub: str) -> UserModel | None:
        result = await self._session.execute(select(UserModel).where(UserModel.cognito_sub == cognito_sub))
        return result.scalar_one_or_none()

    async def delete(self, user: UserModel) -> None:
        await self._session.delete(user)
        await self._session.flush()
