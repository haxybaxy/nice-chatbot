from app.core.cognito import CognitoClient, CognitoTokens


class RefreshSession:
    def __init__(self, cognito: CognitoClient) -> None:
        self._cognito = cognito

    async def execute(self, *, refresh_token: str) -> CognitoTokens:
        return await self._cognito.refresh(refresh_token)
