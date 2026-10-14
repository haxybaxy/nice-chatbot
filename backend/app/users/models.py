"""ORM model for the ``user`` table."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class UserModel(Base, TimestampMixin):
    # `user` is a reserved word: SQLAlchemy and Alembic quote it; raw psql needs "user".
    __tablename__ = "user"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    # The Cognito user id (token `sub`). Every user is created through Cognito, so NOT NULL.
    # The local `id` is the stable primary key; Cognito is linked, not the source of identity.
    cognito_sub: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
