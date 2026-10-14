"""Schema conventions, checked on ``Base.metadata`` (no database): snake_case names, the
timestamp mixin everywhere, tz-aware ``*_at`` datetimes, ``*_id`` foreign keys, explicit
relationship loading (implicit lazy loads raise under the async session), the naming
convention, and the role CHECK in step with the enum."""

import re

from sqlalchemy import CheckConstraint, Date, DateTime

from app.db.base import NAMING_CONVENTION, Base
from app.db.registry import register_all_models
from app.organizations.models import OrganizationRole

register_all_models()

SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
TIMESTAMP_COLUMNS = {"id", "created_at", "updated_at"}
# Anything but SQLAlchemy's implicit default ("select"), which lazy-loads on attribute access.
EXPLICIT_LAZY = {"selectin", "joined", "subquery", "immediate", "raise", "raise_on_sql", "noload"}
QUOTED = re.compile(r"'([^']*)'")


def test_table_and_column_names_are_snake_case() -> None:
    found = [
        name
        for table in Base.metadata.tables.values()
        for name in (table.name, *(f"{table.name}.{column.name}" for column in table.columns))
        if not SNAKE.match(name.rsplit(".", 1)[-1])
    ]
    assert found == []


def test_every_table_has_the_timestamp_columns() -> None:
    found = [
        table.name for table in Base.metadata.tables.values() if not TIMESTAMP_COLUMNS <= set(table.columns.keys())
    ]
    assert found == [], "models inherit Base, TimestampMixin"


def test_temporal_columns_are_aware_and_suffixed() -> None:
    found: list[str] = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            label = f"{table.name}.{column.name}"
            if isinstance(column.type, DateTime):
                if not column.type.timezone:
                    found.append(f"{label}: DateTime(timezone=True)")
                if not column.name.endswith("_at"):
                    found.append(f"{label}: datetime columns end in _at")
            elif isinstance(column.type, Date) and not column.name.endswith("_date"):
                found.append(f"{label}: date columns end in _date")
    assert found == []


def test_foreign_keys_are_suffixed() -> None:
    """``<noun>_id`` for references; ``<verb>_by`` is the audit form (``created_by`` → user)."""
    found = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.foreign_keys and not column.name.endswith(("_id", "_by"))
    ]
    assert found == []


def test_relationships_declare_their_loading() -> None:
    found = [
        f"{mapper.class_.__name__}.{relationship.key}: lazy={relationship.lazy!r}"
        for mapper in Base.registry.mappers
        for relationship in mapper.relationships
        if relationship.lazy not in EXPLICIT_LAZY
    ]
    assert found == [], "declare lazy='selectin' (or 'raise') — an implicit lazy load raises under AsyncSession"


def test_naming_convention_is_complete() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    assert set(NAMING_CONVENTION) == {"ix", "uq", "ck", "fk", "pk"}


def test_role_check_matches_the_enum() -> None:
    table = Base.metadata.tables["organization_member"]
    # Declared as name="role"; the naming convention renders it <table>_<name>_check.
    checks = [
        c for c in table.constraints if isinstance(c, CheckConstraint) and c.name == "organization_member_role_check"
    ]
    assert len(checks) == 1
    literals = set(QUOTED.findall(str(checks[0].sqltext)))
    assert literals == {role.value for role in OrganizationRole}
