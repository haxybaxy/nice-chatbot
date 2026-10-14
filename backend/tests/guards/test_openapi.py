"""The OpenAPI document as a contract.

Auth on every non-public operation, the error envelope on every documented error, the statuses
each operation can actually produce, docs hidden in production, and a committed snapshot so any
wire change is a deliberate, reviewable diff (``just openapi-snapshot`` rewrites it).
"""

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.main import create_app

SNAPSHOT = Path(__file__).with_name("openapi.snapshot.json")
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
BEARER: list[dict[str, list[str]]] = [{"BearerAuth": []}]
ERROR_REF = "#/components/schemas/ErrorOut"
HEALTH_PREFIX = "/api/health"
# The only operations reachable without a bearer token.
PUBLIC_OPERATIONS = {
    ("get", "/api/health"),
    ("get", "/api/health/ready"),
    ("post", "/api/auth/signup"),
    ("post", "/api/auth/signin"),
    ("post", "/api/auth/refresh"),
    ("post", "/api/auth/forgot-password"),
    ("post", "/api/auth/reset-password"),
}
# Documented non-2xx responses that legitimately use another schema.
NON_ENVELOPE_RESPONSES = {("get", "/api/health/ready", "503")}

type JsonObject = dict[str, object]


def _obj(value: object) -> JsonObject:
    assert isinstance(value, dict), f"expected an object, got {type(value).__name__}"
    return cast(JsonObject, value)


def _operations(spec: JsonObject) -> Iterator[tuple[str, str, JsonObject]]:
    for path, item in _obj(spec["paths"]).items():
        for method, operation in _obj(item).items():
            if method in HTTP_METHODS:
                yield method, path, _obj(operation)


def _error_responses(operation: JsonObject) -> dict[str, JsonObject]:
    return {status: _obj(body) for status, body in _obj(operation.get("responses", {})).items() if status >= "400"}


def _schema_ref(response: JsonObject) -> object:
    content = _obj(response.get("content", {}))
    if "application/json" not in content:
        return None
    return _obj(_obj(content["application/json"]).get("schema", {})).get("$ref")


def test_bearer_scheme_is_declared(spec: JsonObject) -> None:
    scheme = _obj(_obj(_obj(spec["components"])["securitySchemes"])["BearerAuth"])
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"


def test_every_non_public_operation_requires_the_bearer(spec: JsonObject) -> None:
    found: list[str] = []
    for method, path, operation in _operations(spec):
        security = operation.get("security")
        if (method, path) in PUBLIC_OPERATIONS:
            if security is not None:
                found.append(f"{method.upper()} {path}: listed as public but declares security")
        elif security != BEARER:
            found.append(
                f"{method.upper()} {path}: no bearer requirement — add CurrentUserDep or list it in PUBLIC_OPERATIONS"
            )
    assert found == []


def test_fastapi_validation_error_schema_is_absent(spec: JsonObject) -> None:
    """Every 422 is documented with the envelope, so FastAPI never emits its own schema."""
    schemas = _obj(_obj(spec["components"])["schemas"])
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas
    assert "ErrorOut" in schemas


def test_documented_errors_use_the_envelope(spec: JsonObject) -> None:
    found = [
        f"{method.upper()} {path} {status}: {_schema_ref(response)!r}"
        for method, path, operation in _operations(spec)
        for status, response in _error_responses(operation).items()
        if (method, path, status) not in NON_ENVELOPE_RESPONSES and _schema_ref(response) != ERROR_REF
    ]
    assert found == [], "declare error responses with app.core.openapi.error_responses(...)"


def test_operations_document_the_errors_they_can_produce(spec: JsonObject) -> None:
    found: list[str] = []
    for method, path, operation in _operations(spec):
        required: set[str] = set()
        if not path.startswith(HEALTH_PREFIX):
            required |= {"500", "503"}
        if operation.get("security"):
            required.add("401")
        parameters = [_obj(p) for p in cast(list[object], operation.get("parameters", []))]
        if any(p.get("in") == "path" for p in parameters):
            required.add("404")
        if parameters or "requestBody" in operation:
            required.add("422")
        missing = sorted(required - set(_error_responses(operation)))
        if missing:
            found.append(f"{method.upper()} {path}: missing responses {missing}")
    assert found == []


async def test_docs_are_served_in_debug_tiers(http: AsyncClient) -> None:
    assert (await http.get("/docs")).status_code == 200
    assert (await http.get("/openapi.json")).status_code == 200


@pytest.fixture
async def production_http(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    """A client over an app built while ENVIRONMENT=prod (docs decisions are taken at construction)."""
    monkeypatch.setattr(settings, "environment", "prod")
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
            yield client
    finally:
        monkeypatch.undo()
        configure_logging()  # create_app() reconfigured logging for the prod tier


async def test_docs_are_hidden_in_production(production_http: AsyncClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert (await production_http.get(path)).status_code == 404, path
    assert (await production_http.get("/api/health")).status_code == 200


def render_spec(spec: JsonObject) -> str:
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def test_openapi_snapshot_is_current(spec: JsonObject, request: pytest.FixtureRequest) -> None:
    rendered = render_spec(spec)
    if request.config.getoption("--update-openapi-snapshot"):
        SNAPSHOT.write_text(rendered, encoding="utf-8")
    current = SNAPSHOT.read_text(encoding="utf-8") if SNAPSHOT.exists() else ""
    assert rendered == current, (
        "the OpenAPI document changed; review the diff and run `just openapi-snapshot` if it is intended"
    )
