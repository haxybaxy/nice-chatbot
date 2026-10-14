from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cognito import CognitoClient
from app.users.models import UserModel
from app.users.repository import UserRepository


class DeleteUser:
    """Delete the local user (memberships cascade) and its Cognito identity."""

    def __init__(self, session: AsyncSession, cognito: CognitoClient) -> None:
        self._users = UserRepository(session)
        self._cognito = cognito

    async def execute(self, *, user: UserModel) -> None:
        # Local row first, flush only: if the Cognito delete fails the request transaction
        # rolls back and nothing is half-deleted. The reverse order has no undo.
        await self._users.delete(user)
        await self._cognito.delete_user(user.email)
