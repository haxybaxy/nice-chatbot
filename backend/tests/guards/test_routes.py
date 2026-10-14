"""Route-table invariants, checked on the live FastAPI app (no HTTP, no database)."""

import inspect
import re
from collections.abc import Iterator
from pathlib import Path
from typing import get_args, get_origin

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext

from app.core.schemas import BaseSchemaOut
from app.db.session import get_db

APP = Path(__file__).resolve().parents[2] / "app"
PATH_PARAM = re.compile(r"\{([^}]+)\}")
PATH_PARAM_NAME = re.compile(r"^[a-z]+(_[a-z]+)*_id$")

type Routes = list[tuple[RouteContext, APIRoute]]


def _label(ctx: RouteContext, route: APIRoute) -> str:
    return f"{','.join(sorted(route.methods or ()))} {ctx.path}"


def _is_async_callable(call: object) -> bool:
    """Coroutine or async-generator function, or an instance whose ``__call__`` is one."""
    if inspect.iscoroutinefunction(call) or inspect.isasyncgenfunction(call):
        return True
    if inspect.isroutine(call) or inspect.isclass(call):
        return False
    dunder = inspect.getattr_static(type(call), "__call__", None)
    return inspect.iscoroutinefunction(dunder) or inspect.isasyncgenfunction(dunder)


def _iter_dependants(root: Dependant) -> Iterator[Dependant]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.dependencies)


def test_every_endpoint_is_a_coroutine(routes: Routes) -> None:
    sync = [_label(ctx, route) for ctx, route in routes if not inspect.iscoroutinefunction(route.endpoint)]
    assert sync == [], "sync handlers run in the threadpool; declare `async def`"


def test_every_dependency_is_async(routes: Routes) -> None:
    """Sync dependencies cost a threadpool hop per request; even pure factories are `async def`."""
    found = [
        f"{_label(ctx, route)}: {getattr(dep.call, '__qualname__', dep.call)}"
        for ctx, route in routes
        for dep in _iter_dependants(route.dependant)
        if dep is not route.dependant and dep.call is not None and not _is_async_callable(dep.call)
    ]
    assert found == []


def test_response_models_are_out_schemas(routes: Routes) -> None:
    """Every operation serializes through a ``BaseSchemaOut`` (or a list of one), except 204s."""
    found: list[str] = []
    for ctx, route in routes:
        model: object = route.response_model
        if route.status_code == 204:
            if model is not None:
                found.append(f"{_label(ctx, route)}: a 204 returns None")
            continue
        if get_origin(model) is list:
            (model,) = get_args(model)
        if not (isinstance(model, type) and issubclass(model, BaseSchemaOut)):
            found.append(f"{_label(ctx, route)}: response model {model!r} is not a *Out schema")
    assert found == []


def test_routes_are_documented(routes: Routes) -> None:
    found = [_label(ctx, route) for ctx, route in routes if not route.summary or not route.tags]
    assert found == [], "every route declares summary= and belongs to a tagged router"


def test_paths_and_params_follow_rest_naming(routes: Routes) -> None:
    found: list[str] = []
    for ctx, route in routes:
        path = ctx.path or ""
        if not path.startswith("/api/"):
            found.append(f"{_label(ctx, route)}: not under /api/")
        found.extend(
            f"{_label(ctx, route)}: path param {{{name}}} must be snake_case and end in _id"
            for name in PATH_PARAM.findall(path)
            if not PATH_PARAM_NAME.match(name)
        )
    assert found == []


def test_every_domain_router_is_included(routes: Routes) -> None:
    served = {route.endpoint.__module__ for _, route in routes}
    missing = [
        f"app.{path.parent.name}.router"
        for path in sorted(APP.glob("*/router.py"))
        if f"app.{path.parent.name}.router" not in served
    ]
    assert missing == [], "include the router in app/api.py"


def test_db_session_commits_before_the_response(routes: Routes) -> None:
    """``DbDep`` must keep ``scope="function"`` so a commit-time failure becomes an error response."""
    found = [
        _label(ctx, route)
        for ctx, route in routes
        for dep in _iter_dependants(route.dependant)
        if dep.call is get_db and dep.scope != "function"
    ]
    assert found == []
