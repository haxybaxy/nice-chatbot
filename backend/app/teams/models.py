"""ORM models for teams — the working groups inside an organization — and their memberships."""

from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.organizations.models import OrganizationMemberModel, OrganizationModel, OrganizationRole
from app.users.models import UserModel


class TeamModel(Base, TimestampMixin):
    __tablename__ = "team"
    # Team names are unique within their organization; `organization_id` leads the constraint,
    # so "teams of this organization" needs no index of its own.
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    # Audit only, like `organization.created_by` — but it also grants member management below.
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"))

    organization: Mapped[OrganizationModel] = relationship(lazy="selectin")

    def is_managed_by(self, user_id: UUID, organization_member: OrganizationMemberModel | None) -> bool:
        """Members are added and removed by the team's creator or an organization owner/admin."""
        if self.created_by == user_id:
            return True
        return organization_member is not None and organization_member.has_role(
            OrganizationRole.OWNER, OrganizationRole.ADMIN
        )


class TeamMemberModel(Base, TimestampMixin):
    """A user's membership in a team. Team members are expected to be members of the team's
    organization; the schema does not enforce that — the caller of ``CreateTeam`` is
    responsible for it (sign-up passes the owner it just created, ``AddTeamMember`` checks)."""

    __tablename__ = "team_member"
    __table_args__ = (UniqueConstraint("team_id", "user_id"),)

    # Leading column of the unique constraint, so it needs no index of its own.
    team_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("team.id", ondelete="CASCADE"))
    # "which teams is this user in" — the other access path.
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), index=True)

    team: Mapped[TeamModel] = relationship(lazy="selectin")
    user: Mapped[UserModel] = relationship(lazy="selectin")
