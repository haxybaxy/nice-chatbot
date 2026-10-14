from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cognito import CognitoClient, CognitoTokens
from app.core.logging_config import get_logger
from app.organizations.models import OrganizationModel
from app.organizations.use_cases.create_organization import CreateOrganization
from app.teams.models import TeamModel
from app.teams.use_cases.create_team import CreateTeam
from app.users.models import UserModel
from app.users.use_cases.create_user import CreateUser

logger = get_logger(__name__)

DEFAULT_TEAM_NAME = "General"
_ORGANIZATION_NAME_SUFFIX = "'s organization"
# `organization.name` is String(255) and `full_name` alone may already be 255 characters, so
# the owner part is what gets truncated — the suffix always survives.
_ORGANIZATION_OWNER_MAX_LENGTH = 255 - len(_ORGANIZATION_NAME_SUFFIX)


def _default_organization_name(*, email: str, full_name: str | None) -> str:
    """``"<full name>'s organization"``, falling back to the email's local part."""
    owner = full_name or email.split("@", 1)[0]
    return owner[:_ORGANIZATION_OWNER_MAX_LENGTH] + _ORGANIZATION_NAME_SUFFIX


@dataclass(frozen=True, slots=True)
class AuthSession:
    user: UserModel
    organization: OrganizationModel
    team: TeamModel
    tokens: CognitoTokens


class SignUp:
    """Create the Cognito identity, the local user with a personal organization and a default
    team, and sign the new user in.

    The user, organization, membership and team rows are written through the one request
    session, so they commit — or roll back — together. Cognito is the authoritative uniqueness
    check, so it goes first. If anything fails after the Cognito user exists, that user is
    deleted again (best effort) so a retry with the same email doesn't hit a 409. Remaining gap:
    a failure of the request transaction's commit — after this use case returns — would leave an
    orphan Cognito user.
    """

    def __init__(self, session: AsyncSession, cognito: CognitoClient) -> None:
        self._create_user = CreateUser(session)
        self._create_organization = CreateOrganization(session)
        self._create_team = CreateTeam(session)
        self._cognito = cognito

    async def execute(self, *, email: str, password: str, full_name: str | None) -> AuthSession:
        sub = await self._cognito.create_user(email, full_name=full_name)
        try:
            await self._cognito.set_permanent_password(email, password)
            user = await self._create_user.execute(email=email, full_name=full_name, cognito_sub=sub)
            organization = await self._create_organization.execute(
                name=_default_organization_name(email=email, full_name=full_name), creator=user
            )
            team = await self._create_team.execute(organization=organization, name=DEFAULT_TEAM_NAME, creator=user)
            tokens = await self._cognito.password_auth(email, password)
        except Exception:
            await self._rollback_identity(email)
            raise
        logger.info("user signed up", user_id=str(user.id), organization_id=str(organization.id), team_id=str(team.id))
        return AuthSession(user=user, organization=organization, team=team, tokens=tokens)

    async def _rollback_identity(self, email: str) -> None:
        try:
            await self._cognito.delete_user(email)
        except Exception:
            logger.exception("failed to roll back cognito user after sign-up failure")
