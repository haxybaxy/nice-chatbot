from app.core.cognito import CognitoClient, CognitoTokens


class SignIn:
    """Password sign-in. Returns tokens only; the client fetches its profile from ``/users/me``."""

    def __init__(self, cognito: CognitoClient) -> None:
        self._cognito = cognito

    async def execute(self, *, email: str, password: str) -> CognitoTokens:
        return await self._cognito.password_auth(email, password)
