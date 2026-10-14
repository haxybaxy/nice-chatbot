from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import UserModel
from app.users.repository import UserRepository


class UpdateUser:
    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)

    async def execute(self, *, user: UserModel, full_name: str | None) -> UserModel:
        if full_name is not None:
            user.full_name = full_name
        return await self._users.save(user)
