"""Data access for password-reset links. Flushes, never commits — ``get_db`` owns the transaction."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import PasswordResetTokenModel


class PasswordResetTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, token: PasswordResetTokenModel) -> PasswordResetTokenModel:
        self._session.add(token)
        await self._session.flush()
        await self._session.refresh(token)
        return token

    async def get_by_token_hash(self, token_hash: str) -> PasswordResetTokenModel | None:
        result = await self._session.execute(
            select(PasswordResetTokenModel).where(PasswordResetTokenModel.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def delete_for_user(self, user_id: UUID) -> None:
        """Drop every outstanding link of the user: a new request replaces the old one, redeeming consumes it."""
        await self._session.execute(delete(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == user_id))
        await self._session.flush()
