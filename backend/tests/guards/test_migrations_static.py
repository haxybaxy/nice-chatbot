"""Migrations are static, reversible and named: no imports from ``app`` (a migration must not
change when the models do), a real ``downgrade``, and the dated ``<date>-<rev>_<slug>`` filename
``alembic.ini`` produces when ``-m`` is given."""

import ast
import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "app" / "db" / "migrations" / "versions"
FILENAME = re.compile(r"^\d{4}_\d{2}_\d{2}_\d{4}-[0-9a-f]{12}_[a-z0-9_]+\.py$")


def _migrations() -> list[Path]:
    return sorted(path for path in VERSIONS.glob("*.py") if path.name != "__init__.py")


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _is_trivial(function: ast.FunctionDef) -> bool:
    body = [
        node
        for node in function.body
        if not isinstance(node, ast.Pass)
        and not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        )
    ]
    return not body


def test_there_is_at_least_one_migration() -> None:
    assert _migrations()


def test_filenames_are_dated_and_slugged() -> None:
    found = [path.name for path in _migrations() if not FILENAME.match(path.name)]
    assert found == [], 'generate with `just migration "<slug>"` — the slug is required'


def test_migrations_are_reversible() -> None:
    found: list[str] = []
    for path in _migrations():
        functions = _functions(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for name in ("upgrade", "downgrade"):
            function = functions.get(name)
            if function is None:
                found.append(f"{path.name}: missing {name}()")
            elif _is_trivial(function):
                found.append(f"{path.name}: {name}() does nothing")
    assert found == []


def test_migrations_do_not_import_the_app() -> None:
    found: list[str] = []
    for path in _migrations():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            found.extend(
                f"{path.name}:{node.lineno} imports {m}" for m in modules if m == "app" or m.startswith("app.")
            )
    assert found == [], "migrations must be static: copy what you need, never import models"
