"""Enumerate the app's API operations. Shared by the guards and the route-coverage check.

``app.routes`` holds lazily-included routers rather than ``APIRoute`` objects; FastAPI's own
OpenAPI generation walks ``iter_route_contexts``, and so does everything here. ``ctx.path`` is
the effective, prefixed path (``/api/auth/signup``); ``route`` is the original ``APIRoute``.
"""

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts


def iter_api_routes(app: FastAPI) -> Iterator[tuple[RouteContext, APIRoute]]:
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        if isinstance(route, APIRoute):
            yield ctx, route
