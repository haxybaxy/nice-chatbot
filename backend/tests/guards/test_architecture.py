"""Import and layout rules for ``app/``, enforced rather than just documented.

* Cross-domain: a domain may import another domain's ``models`` and ``use_cases`` (its public
  surface), never its ``repository``, ``schemas``, ``router`` or ``dependencies``.
* Layering inside a domain: use cases and repositories never see HTTP schemas or FastAPI;
  routers never see repositories or SQLAlchemy; models never see pydantic; boundary schemas
  never see ``datetime`` (they use ``UtcDatetime``).
* Composition roots (``app/api.py``, ``app/main.py``) are imported by nothing under ``app/``.
* Transactions commit in exactly one place (``app/db/session.py``); routers never serialize.
* Naming: ``*Model``, ``*Repository``, ``<verb_noun>_use_case`` → ``*Dep``; domain code raises
  only ``AppError``; every router has an HTTP test.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

from app.db.base import Base, TimestampMixin
from app.db.registry import register_all_models

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
TESTS = BACKEND / "tests"

INFRA_PACKAGES = {"core", "db"}
DOMAINS = {
    p.name for p in APP.iterdir() if p.is_dir() and p.name not in INFRA_PACKAGES and not p.name.startswith(("_", "."))
}
DOMAIN_ENTRIES = {
    "__init__.py",
    "models.py",
    "schemas.py",
    "repository.py",
    "dependencies.py",
    "router.py",
    "use_cases",
}
PRIVATE_MODULES = {"repository", "schemas", "router", "dependencies"}
COMPOSITION_ROOTS = {"app.api", "app.main"}
# (file under app/, imported module): the sanctioned exceptions to the cross-domain rule.
ALLOWED_CROSS_DOMAIN = {("core/security.py", "app.users.repository")}
# Per module kind: top-level packages and in-domain module kinds it must not import.
FORBIDDEN_IMPORTS: dict[str, frozenset[str]] = {
    "use_cases": frozenset({"schemas", "router", "dependencies", "fastapi"}),
    "router": frozenset({"repository", "sqlalchemy"}),
    "repository": frozenset({"fastapi", "schemas", "use_cases", "dependencies", "router"}),
    "models": frozenset({"fastapi", "pydantic", "schemas", "repository", "use_cases", "dependencies", "router"}),
    "schemas": frozenset({"sqlalchemy", "repository", "use_cases", "dependencies", "router", "datetime"}),
}
SERIALIZATION_NAMES = {"model_validate", "model_dump", "model_dump_json", "JSONResponse", "jsonable_encoder"}
RAISES_ONLY_APP_ERROR = {"use_cases", "repository", "dependencies"}


def _modules() -> Iterator[tuple[str, ast.Module]]:
    """(path relative to app/, AST) for every module except migrations (guarded separately)."""
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        if rel.startswith("db/migrations/"):
            continue
        yield rel, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.Module) -> Iterator[tuple[int, str]]:
    """(line, dotted name) for every import; ``from a.b import c`` yields both ``a.b`` and ``a.b.c``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            yield node.lineno, node.module
            for alias in node.names:
                yield node.lineno, f"{node.module}.{alias.name}"


def _kind(rel: str) -> str | None:
    """Module kind for the layering rules, or None for infrastructure and composition roots."""
    parts = rel.split("/")
    if parts[0] not in DOMAINS:
        return None
    if len(parts) == 3 and parts[1] == "use_cases":
        return "use_cases"
    if len(parts) == 2:
        return parts[1].removesuffix(".py")
    return None


def _domain_kind(module: str) -> str | None:
    """``app.<domain>.<kind>...`` → ``<kind>`` when the import targets a domain module."""
    parts = module.split(".")
    if len(parts) >= 3 and parts[0] == "app" and parts[1] in DOMAINS:
        return parts[2]
    return None


def test_domains_were_discovered() -> None:
    assert DOMAINS, "no domain packages under app/ — the guards would silently check nothing"


def test_no_private_cross_domain_imports() -> None:
    found: list[str] = []
    for rel, tree in _modules():
        if "/" not in rel:
            continue  # composition roots wire everything together
        owner = rel.split("/", 1)[0]
        for line, module in _imports(tree):
            parts = module.split(".")
            if len(parts) < 3 or parts[0] != "app" or parts[1] not in DOMAINS or parts[2] not in PRIVATE_MODULES:
                continue
            target = ".".join(parts[:3])
            if parts[1] == owner or (rel, target) in ALLOWED_CROSS_DOMAIN:
                continue
            found.append(f"{rel}:{line} imports {target}")
    assert found == []


def test_composition_roots_are_imported_by_nothing() -> None:
    found = [
        f"{rel}:{line} imports {module}"
        for rel, tree in _modules()
        if "/" in rel
        for line, module in _imports(tree)
        if module in COMPOSITION_ROOTS or module.startswith(tuple(f"{root}." for root in COMPOSITION_ROOTS))
    ]
    assert found == []


def test_domain_packages_contain_only_the_sanctioned_modules() -> None:
    found: list[str] = []
    for domain in sorted(DOMAINS):
        for entry in sorted((APP / domain).iterdir()):
            if entry.name == "__pycache__":
                continue
            if entry.name not in DOMAIN_ENTRIES:
                found.append(f"{domain}/{entry.name}: not one of {sorted(DOMAIN_ENTRIES)}")
            if entry.name == "use_cases":
                for child in sorted(entry.iterdir()):
                    if child.name != "__pycache__" and (child.is_dir() or child.suffix != ".py"):
                        found.append(f"{domain}/use_cases/{child.name}: use_cases holds one .py per use case")
    assert found == []


def test_no_tests_under_app() -> None:
    assert sorted(p.relative_to(APP).as_posix() for p in APP.rglob("test_*.py")) == []


def test_layering_inside_domains() -> None:
    found: list[str] = []
    for rel, tree in _modules():
        kind = _kind(rel)
        forbidden = FORBIDDEN_IMPORTS.get(kind or "")
        if forbidden is None:
            continue
        for line, module in _imports(tree):
            top = module.split(".", 1)[0]
            if top in forbidden or _domain_kind(module) in forbidden:
                found.append(f"{rel}:{line} ({kind}) imports {module}")
    assert found == []


def test_routers_do_not_catch_or_serialize() -> None:
    """Errors leave through the exception handlers; ``response_model`` does the serializing."""
    found: list[str] = []
    for rel, tree in _modules():
        if _kind(rel) != "router":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                found.append(f"{rel}:{node.lineno} try/except in a router")
            elif isinstance(node, ast.Attribute) and node.attr in SERIALIZATION_NAMES:
                found.append(f"{rel}:{node.lineno} .{node.attr}")
            elif isinstance(node, ast.Name) and node.id in SERIALIZATION_NAMES:
                found.append(f"{rel}:{node.lineno} {node.id}")
    assert found == []


def test_transactions_commit_only_in_the_session_dependency() -> None:
    found = [
        f"{rel}:{node.lineno} .{node.func.attr}()"
        for rel, tree in _modules()
        if rel != "db/session.py"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"commit", "rollback"}
    ]
    assert found == []


def test_domain_code_raises_only_app_errors() -> None:
    found: list[str] = []
    for rel, tree in _modules():
        if _kind(rel) not in RAISES_ONLY_APP_ERROR:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue  # bare re-raise
            func = node.exc.func if isinstance(node.exc, ast.Call) else None
            if not (
                isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "AppError"
            ):
                found.append(f"{rel}:{node.lineno} raises {ast.unparse(node.exc)}")
    assert found == []


def test_naming_conventions() -> None:
    register_all_models()
    found: list[str] = []
    for mapper in Base.registry.mappers:
        name = mapper.class_.__name__
        if not name.endswith("Model"):
            found.append(f"{name}: ORM classes end in Model")
        if TimestampMixin not in mapper.class_.__mro__:
            found.append(f"{name}: ORM classes inherit TimestampMixin")
    for rel, tree in _modules():
        kind = _kind(rel)
        if kind == "repository":
            found.extend(
                f"{rel}: {node.name} — repository classes end in Repository"
                for node in tree.body
                if isinstance(node, ast.ClassDef) and not node.name.endswith("Repository")
            )
        elif kind == "dependencies":
            found.extend(_dependency_naming(rel, tree))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "get_logger":
                arg = node.args[0] if len(node.args) == 1 and not node.keywords else None
                if not (isinstance(arg, ast.Name) and arg.id == "__name__"):
                    found.append(f"{rel}:{node.lineno} get_logger must be called with __name__")
    assert found == []


def _dependency_naming(rel: str, tree: ast.Module) -> list[str]:
    """``*_use_case`` factories are async and return a use case; ``Annotated`` aliases end in Dep."""
    found: list[str] = []
    use_case_classes = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and _domain_kind(node.module or "") == "use_cases"
        for alias in node.names
    }
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            returns_use_case = isinstance(node.returns, ast.Name) and node.returns.id in use_case_classes
            if returns_use_case and not node.name.endswith("_use_case"):
                found.append(f"{rel}:{node.lineno} {node.name} returns a use case; name it <verb_noun>_use_case")
            if node.name.endswith("_use_case") and not (returns_use_case and isinstance(node, ast.AsyncFunctionDef)):
                found.append(f"{rel}:{node.lineno} {node.name} must be `async def` and return the use case")
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            value = node.value
            is_annotated = (
                isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name) and value.value.id == "Annotated"
            )
            if is_annotated and isinstance(target, ast.Name) and not target.id.endswith("Dep"):
                found.append(f"{rel}:{node.lineno} {target.id}: Annotated dependency aliases end in Dep")
    return found


def test_every_router_has_an_http_test() -> None:
    missing = [
        f"tests/{domain}/test_{domain}_router.py"
        for domain in sorted(DOMAINS)
        if (APP / domain / "router.py").exists() and not (TESTS / domain / f"test_{domain}_router.py").exists()
    ]
    assert missing == []
