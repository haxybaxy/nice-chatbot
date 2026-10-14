"""ORM model for password-reset links.

A row is one outstanding link. Only the SHA-256 of the token is stored — the raw token exists in
the email alone — and redeeming the link deletes the row, so there is no ``used_at``.
"""

import hashlib
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.users.models import UserModel


class PasswordResetTokenModel(Base, TimestampMixin):
    __tablename__ = "password_reset_token"

    # "the user's outstanding links" — replaced on every request, dropped with the user.
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), index=True)
    # SHA-256 hex of the raw token; the unique index is the lookup path on redemption.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # `selectin` loads the user with the token query — no implicit lazy load, which would raise
    # under the async session.
    user: Mapped[UserModel] = relationship(lazy="selectin")

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """The storable form of a reset token."""
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
