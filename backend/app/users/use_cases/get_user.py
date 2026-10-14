from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.users.models import UserModel
from app.users.repository import UserRepository


class GetUser:
    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)

    async def execute(self, *, user_id: UUID) -> UserModel:
        """The user with this id, or 404. A row already loaded in this session (the
        authenticated user) is served from the identity map without a query."""
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise AppError.not_found("User", user_id)
        return user
