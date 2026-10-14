from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.users.models import UserModel
from app.users.repository import UserRepository


class CreateUser:
    """Persist the local row for an identity that already exists in Cognito.

    Called by auth sign-up. Flush only — the caller's request transaction commits.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)

    async def execute(self, *, email: str, full_name: str | None, cognito_sub: str) -> UserModel:
        if await self._users.get_by_email(email) is not None:
            # The unique constraint is the backstop (→ 409 via the IntegrityError handler).
            raise AppError.conflict("An account with this email already exists")
        return await self._users.add(UserModel(email=email, full_name=full_name, cognito_sub=cognito_sub))
