"""Boundary-schema rules: every schema derives from the shared bases, ``*In``/``*Out`` naming,
bounded string inputs, no secrets in outputs, and the base config that the wire format relies on."""

import importlib
import types
from pathlib import Path
from typing import Union, get_args, get_origin

from annotated_types import MaxLen
from pydantic import BaseModel, StringConstraints  # noqa: TID251
from pydantic.alias_generators import to_camel
from pydantic.fields import FieldInfo

from app.core.schemas import BaseSchema, BaseSchemaOut

APP = Path(__file__).resolve().parents[2] / "app"
BASES = {BaseSchema, BaseSchemaOut}
# Field names that must never appear on a response schema.
SENSITIVE_FIELDS = {"password", "cognito_sub", "client_secret", "aws_secret_access_key", "secret"}


def _schema_modules() -> list[str]:
    domain_modules = [f"app.{path.parent.name}.schemas" for path in sorted(APP.glob("*/schemas.py"))]
    return ["app.core.schemas", "app.api", *domain_modules]


def _schema_classes() -> list[type[BaseModel]]:
    classes: list[type[BaseModel]] = []
    for name in _schema_modules():
        module = importlib.import_module(name)
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, BaseModel) and value.__module__ == name:
                classes.append(value)
    return classes


def _unwrap_optional(annotation: object) -> object:
    if get_origin(annotation) in (Union, types.UnionType):
        members = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(members) == 1:
            return members[0]
    return annotation


def _is_bounded(field: FieldInfo) -> bool:
    return any(
        isinstance(meta, MaxLen) or (isinstance(meta, StringConstraints) and meta.max_length is not None)
        for meta in field.metadata
    )


def test_every_schema_derives_from_the_shared_bases() -> None:
    found = [cls.__name__ for cls in _schema_classes() if cls not in BASES and not issubclass(cls, BaseSchema)]
    assert found == []


def test_schema_names_say_which_direction_they_face() -> None:
    found: list[str] = []
    for cls in _schema_classes():
        if cls in BASES:
            continue
        expected = "Out" if issubclass(cls, BaseSchemaOut) else "In"
        if not cls.__name__.endswith(expected):
            found.append(f"{cls.__module__}.{cls.__name__}: should end in {expected}")
    assert found == []


def test_string_inputs_are_bounded() -> None:
    """A plain ``str`` request field needs ``max_length`` (``Field`` or ``StringConstraints``)."""
    found = [
        f"{cls.__name__}.{name}"
        for cls in _schema_classes()
        if cls not in BASES and not issubclass(cls, BaseSchemaOut)
        for name, field in cls.model_fields.items()
        if _unwrap_optional(field.annotation) is str and not _is_bounded(field)
    ]
    assert found == []


def test_outputs_never_expose_secrets() -> None:
    found = [
        f"{cls.__name__}.{name}"
        for cls in _schema_classes()
        if issubclass(cls, BaseSchemaOut)
        for name in cls.model_fields
        if name in SENSITIVE_FIELDS
    ]
    assert found == []


def test_base_config_carries_the_wire_contract() -> None:
    assert BaseSchema.model_config.get("extra") == "forbid"
    assert BaseSchema.model_config.get("alias_generator") is to_camel
    assert BaseSchema.model_config.get("str_strip_whitespace") is True
    # Re-declared on the subclass, so a wrong edit there would silently drop the aliasing.
    assert BaseSchemaOut.model_config.get("alias_generator") is to_camel
    assert BaseSchemaOut.model_config.get("from_attributes") is True
