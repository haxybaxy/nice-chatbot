"""Settings live only in ``config.py`` modules, one field per env var, and ``.env.example``
documents exactly those variables."""

import importlib
import pkgutil
import re
from pathlib import Path

from pydantic_settings import BaseSettings  # noqa: TID251

import app

BACKEND = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = BACKEND / ".env.example"
ENV_LINE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=")
# Read by tests/conftest.py, not by the app.
TEST_ONLY_VARS = {"TEST_DATABASE_URL"}
SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


def _settings_classes() -> list[type[BaseSettings]]:
    classes: list[type[BaseSettings]] = []
    for info in pkgutil.walk_packages(app.__path__, prefix="app."):
        if info.name.startswith("app.db.migrations"):
            continue  # env.py runs Alembic on import
        module = importlib.import_module(info.name)
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, BaseSettings) and value.__module__ == info.name:
                classes.append(value)
    return classes


def _env_example_vars() -> set[str]:
    found: set[str] = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = ENV_LINE.match(line)
        if match:
            found.add(match.group(1))
    return found


def test_settings_classes_live_in_config_modules() -> None:
    classes = _settings_classes()
    assert classes, "no BaseSettings subclasses found under app/"
    misplaced = [f"{cls.__module__}.{cls.__name__}" for cls in classes if cls.__module__.rsplit(".", 1)[-1] != "config"]
    assert misplaced == []


def test_fields_are_snake_case_and_claimed_once() -> None:
    seen: dict[str, str] = {}
    found: list[str] = []
    for cls in _settings_classes():
        for name in cls.model_fields:
            if not SNAKE.match(name):
                found.append(f"{cls.__name__}.{name}: not snake_case")
            if name in seen:
                found.append(f"{cls.__name__}.{name}: env var already claimed by {seen[name]}")
            seen[name] = cls.__name__
    assert found == []


def test_env_example_documents_every_setting() -> None:
    fields = {name.upper() for cls in _settings_classes() for name in cls.model_fields}
    documented = _env_example_vars()
    assert sorted(fields - documented) == [], "add the variable to .env.example (commented out is fine)"
    assert sorted(documented - fields - TEST_ONLY_VARS) == [], "remove the variable from .env.example or add a field"
