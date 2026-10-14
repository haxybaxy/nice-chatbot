from app.core.cognito import CognitoClient
from app.core.exceptions import AppError
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class SignOut:
    """Revoke every session of the token's user. Best effort: an already-revoked or expired
    token is not an error worth surfacing — from the client's point of view it is signed out."""

    def __init__(self, cognito: CognitoClient) -> None:
        self._cognito = cognito

    async def execute(self, *, access_token: str) -> None:
        try:
            await self._cognito.global_sign_out(access_token)
        except AppError as error:
            logger.warning("sign-out not applied", error_code=error.code)
