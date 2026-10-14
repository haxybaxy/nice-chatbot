"""ORM models for organizations and their memberships."""

from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.users.models import UserModel


class OrganizationRole(StrEnum):
    """Stored as a plain string column (with a CHECK), so adding a value is a code change
    plus a migration of the constraint — no ``ALTER TYPE``."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class OrganizationModel(Base, TimestampMixin):
    __tablename__ = "organization"

    name: Mapped[str] = mapped_column(String(255))
    # Audit only — ownership is the `owner` membership row, not this column.
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"))


class OrganizationMemberModel(Base, TimestampMixin):
    __tablename__ = "organization_member"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="role"),
    )

    # Leading column of the unique constraint, so it needs no index of its own.
    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE")
    )
    # "which organizations is this user in" — the other access path.
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))

    # `selectin` loads the user eagerly with the membership query — no implicit lazy load,
    # which would raise under the async session.
    user: Mapped[UserModel] = relationship(lazy="selectin")

    def has_role(self, *roles: OrganizationRole) -> bool:
        return self.role in {role.value for role in roles}
