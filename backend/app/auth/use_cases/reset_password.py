"""Redeem a password-reset link: set the new password in Cognito, revoke the user's sessions and
consume the link."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import PasswordResetTokenModel
from app.auth.repository import PasswordResetTokenRepository
from app.core.cognito import CognitoClient
from app.core.exceptions import AppError
from app.core.logging_config import get_logger
from app.users.models import UserModel

logger = get_logger(__name__)


class ResetPassword:
    """Cognito is updated before the link is consumed: a rejected password (policy) or an
    unavailable identity provider raises first, the request rolls back and the same link can be
    retried. Session revocation is best effort — the password is already changed by then.
    """

    def __init__(self, session: AsyncSession, cognito: CognitoClient) -> None:
        self._tokens = PasswordResetTokenRepository(session)
        self._cognito = cognito

    async def execute(self, *, token: str, password: str) -> None:
        reset = await self._tokens.get_by_token_hash(PasswordResetTokenModel.hash_token(token))
        if reset is None or reset.expires_at <= datetime.now(UTC):
            raise AppError.bad_request("Invalid or expired reset link")
        user = reset.user
        await self._cognito.set_permanent_password(user.email, password)
        await self._revoke_sessions(user)
        await self._tokens.delete_for_user(user.id)
        logger.info("password reset", user_id=str(user.id))

    async def _revoke_sessions(self, user: UserModel) -> None:
        try:
            await self._cognito.admin_global_sign_out(user.email)
        except AppError as error:
            logger.warning("sessions not revoked after password reset", user_id=str(user.id), error_code=error.code)
