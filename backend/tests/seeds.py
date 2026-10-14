"""Seed helpers: async, take the session first, flush, return the model."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import PasswordResetTokenModel
from app.organizations.models import OrganizationMemberModel, OrganizationModel, OrganizationRole
from app.users.models import UserModel


async def seed_user(
    db: AsyncSession, *, email: str, full_name: str | None = None, cognito_sub: str | None = None
) -> UserModel:
    user = UserModel(email=email, full_name=full_name, cognito_sub=cognito_sub or str(uuid4()))
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def seed_organization(db: AsyncSession, *, name: str, owner: UserModel) -> OrganizationModel:
    """An organization with ``owner`` as its owner member."""
    organization = OrganizationModel(name=name, created_by=owner.id)
    db.add(organization)
    await db.flush()
    await seed_member(db, organization, owner, OrganizationRole.OWNER)
    await db.refresh(organization)
    return organization


async def seed_member(
    db: AsyncSession, organization: OrganizationModel, user: UserModel, role: OrganizationRole
) -> OrganizationMemberModel:
    member = OrganizationMemberModel(organization_id=organization.id, user_id=user.id, role=role.value, user=user)
    db.add(member)
    await db.flush()
    return member


async def seed_password_reset_token(
    db: AsyncSession, *, user: UserModel, raw_token: str, expires_in: timedelta = timedelta(minutes=30)
) -> PasswordResetTokenModel:
    """An outstanding reset link for ``user`` (``expires_in`` may be negative for an expired one)."""
    token = PasswordResetTokenModel(
        user_id=user.id,
        token_hash=PasswordResetTokenModel.hash_token(raw_token),
        expires_at=datetime.now(UTC) + expires_in,
    )
    db.add(token)
    await db.flush()
    await db.refresh(token)
    return token
