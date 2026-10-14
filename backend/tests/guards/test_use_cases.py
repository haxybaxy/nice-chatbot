"""Use-case shape: one class per file with ``__init__(session[, cognito, mail])`` and a keyword-only
``async execute``, no other public methods. Result types are ``@dataclass``es next to the use
case (never schemas — ``test_architecture`` forbids the import)."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
INIT_PARAMS = {"session", "cognito", "mail"}


def _is_dataclass(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name) and target.id == "dataclass":
            return True
    return False


def _check_use_case(rel: str, cls: ast.ClassDef) -> list[str]:
    problems: list[str] = []
    methods = {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)}
    init = methods.get("__init__")
    if init is None:
        problems.append(f"{rel}: {cls.name} needs __init__(session[, cognito, mail]) — the constructor is the DI seam")
    else:
        extra = {arg.arg for arg in init.args.args[1:]} - INIT_PARAMS
        if extra or init.args.kwonlyargs or init.args.vararg or init.args.kwarg:
            problems.append(f"{rel}: {cls.name}.__init__ takes only session, cognito and/or mail, not {sorted(extra)}")
    execute = methods.get("execute")
    if not isinstance(execute, ast.AsyncFunctionDef):
        problems.append(f"{rel}: {cls.name} needs `async def execute`")
    elif len(execute.args.args) != 1 or execute.args.posonlyargs or execute.args.vararg:
        problems.append(f"{rel}: {cls.name}.execute takes business arguments keyword-only (`self, *, ...`)")
    public = sorted(name for name in methods if not name.startswith("_") and name != "execute")
    if public:
        problems.append(f"{rel}: {cls.name} has extra public methods {public}; make each its own use case")
    return problems


def test_use_case_files_have_the_documented_shape() -> None:
    problems: list[str] = []
    for path in sorted(APP.glob("*/use_cases/*.py")):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        use_cases = [cls for cls in classes if not _is_dataclass(cls)]
        if len(use_cases) != 1:
            problems.append(f"{rel}: one use-case class per file, found {[cls.name for cls in use_cases]}")
        for cls in use_cases:
            problems.extend(_check_use_case(rel, cls))
    assert problems == []
