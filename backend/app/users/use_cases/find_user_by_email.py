from sqlalchemy.ext.asyncio import AsyncSession

from app.users.models import UserModel
from app.users.repository import UserRepository


class FindUserByEmail:
    """Non-raising lookup, for flows that branch on existence (e.g. inviting a member)."""

    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)

    async def execute(self, *, email: str) -> UserModel | None:
        return await self._users.get_by_email(email)
