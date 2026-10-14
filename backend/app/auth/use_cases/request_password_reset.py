"""Mail a password-reset link. Always succeeds from the outside: an unknown address gets no mail
and no error, so the endpoint cannot be used to enumerate accounts."""

import html
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import PasswordResetTokenModel
from app.auth.repository import PasswordResetTokenRepository
from app.core.config import mail_settings, settings
from app.core.logging_config import get_logger
from app.core.mail import Mail, MailClient
from app.users.use_cases.find_user_by_email import FindUserByEmail

logger = get_logger(__name__)

RESET_TOKEN_TTL = timedelta(minutes=30)
# 32 random bytes → a 43-character URL-safe token; the store keeps only its SHA-256.
_TOKEN_BYTES = 32


def _reset_mail(*, to: str, reset_url: str) -> Mail:
    minutes = int(RESET_TOKEN_TTL.total_seconds() // 60)
    text = (
        "Someone asked to reset the password of your account. Open this link to choose a new one:\n\n"
        f"{reset_url}\n\n"
        f"The link works once and expires in {minutes} minutes. "
        "If you did not ask for a reset, you can ignore this email; your password stays the same.\n"
    )
    href = html.escape(reset_url, quote=True)
    html_body = (
        "<p>Someone asked to reset the password of your account. Open this link to choose a new one:</p>"
        f'<p><a href="{href}">{href}</a></p>'
        f"<p>The link works once and expires in {minutes} minutes. "
        "If you did not ask for a reset, you can ignore this email; your password stays the same.</p>"
    )
    return Mail(to=to, subject=f"Reset your {mail_settings.sender_name} password", text=text, html=html_body)


class RequestPasswordReset:
    """Replace the user's outstanding reset link with a fresh one and mail it.

    The token row is flushed before the send: a failed send raises, the request rolls back, and
    no link that was never delivered stays redeemable.
    """

    def __init__(self, session: AsyncSession, mail: MailClient) -> None:
        self._find_user = FindUserByEmail(session)
        self._tokens = PasswordResetTokenRepository(session)
        self._mail = mail

    async def execute(self, *, email: str) -> None:
        user = await self._find_user.execute(email=email)
        if user is None:
            logger.info("password reset requested for an unknown email")
            return
        await self._tokens.delete_for_user(user.id)
        raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
        await self._tokens.add(
            PasswordResetTokenModel(
                user_id=user.id,
                token_hash=PasswordResetTokenModel.hash_token(raw_token),
                expires_at=datetime.now(UTC) + RESET_TOKEN_TTL,
            )
        )
        reset_url = f"{settings.frontend_url}/auth/reset-password?token={raw_token}"
        await self._mail.send(_reset_mail(to=user.email, reset_url=reset_url))
        logger.info("password reset mail sent", user_id=str(user.id))
