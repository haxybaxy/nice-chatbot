# CLAUDE.md — backend

Guidance for working in `backend/`. `README.md` has the quick start; this file has the rules.
Most rules here are **enforced**: ruff (`pyproject.toml`), basedpyright, the guard tests in
`tests/guards/` (DB-free, run by pre-commit on every commit) and the full suite in CI. When a
gate fails, fix the code to match the convention; do not loosen the gate.

## Commands (run from `backend/`)

```bash
uv sync                          # install
just dev                         # uvicorn with reload on :8000
just check                       # fmt + lint + typecheck + deadcode + deps + audit + lock-check + guards — before every commit
just guards                      # tests/guards only (architecture, routes, OpenAPI, schemas, settings, DB, migrations) — no Docker
just test                        # pytest (needs `just db-up`); `just test -k signup` for a subset
uv run pytest tests/auth/test_auth_router.py::TestSignUp -q      # one file / class / test
just openapi-snapshot            # after an intentional API change: rewrite tests/guards/openapi.snapshot.json, then `just contract-refresh` in frontend/
just migration "msg" && just migrate && just migrate-check
```

Python 3.13 · uv · FastAPI · async SQLAlchemy 2 (`postgresql+psycopg`) · Alembic · pydantic v2 ·
structlog · pyjwt · boto3 (Cognito, SES). Follows
[fastapi-best-practices](https://github.com/zhanymkanov/fastapi-best-practices); deliberate
divergences: one central `AppError` instead of per-domain `exceptions.py`, singular table names,
`asyncio.to_thread` rather than `run_in_threadpool`.

## Layout: package-by-feature, one file per concern

```
app/<domain>/
├── models.py          SQLAlchemy ORM (*Model) — the entities
├── schemas.py         Pydantic *In / *Out for the HTTP boundary
├── repository.py      SQL access (*Repository), returns *Model; flush(), never commit()
├── dependencies.py    FastAPI factories: async <verb_noun>_use_case(db: DbDep) → <VerbNoun>Dep
├── router.py          APIRouter; decode → use case → return the domain object (response_model=*Out serializes it once)
└── use_cases/         one class per file: __init__(session[, cognito, mail]) + async execute(*, ...)
```

A domain directory contains exactly these entries (guard: no `service.py`, `utils.py`, …).
`app/core` (config, errors, logging, middleware, Cognito and SES mail adapters, JWT security,
schema bases, OpenAPI helpers), `app/db` (Base, engine, `get_db`, model registry, DB settings, migrations),
`app/api.py` (router composition + health), `app/main.py` (app factory). Nothing under `app/`
imports `api.py` or `main.py` (guard).

### Use-case shape

```python
class InviteMember:
    def __init__(self, session: AsyncSession) -> None:
        self._find_user = FindUserByEmail(session)      # compose other use cases by session
        self._members = OrganizationMemberRepository(session)

    async def execute(self, *, actor: OrganizationMemberModel, email: str, role: OrganizationRole) -> OrganizationMemberModel:
        ...                                             # business args keyword-only; return models, never schemas
```

The constructor is the DI seam and takes only `session`, `cognito` and/or `mail`; `execute` is the
single public method and carries only keyword business arguments; raise `AppError.<factory>()`
on rule violations. A result that spans several objects is a frozen `@dataclass` next to the use
case (`AuthSession`). Need a second lookup? Write a second use case (`FindUserByEmail`), not a
second method. (`tests/guards/test_use_cases.py`.)

### Import rules (`tests/guards/test_architecture.py`)

- A domain may import another domain's `models` and `use_cases`. It may **never** import another
  domain's `repository`, `schemas`, `router` or `dependencies`. The one sanctioned exception is
  `app/core/security.py` → `app.users.repository` (token subject → user). Domains are discovered
  from the filesystem — nothing to register.
- Inside a domain: `use_cases/` never import `schemas`, `fastapi`, `router`, `dependencies`;
  `router.py` never imports `repository` or `sqlalchemy` and contains no `try`; `repository.py`
  never imports `fastapi`, `schemas`, `use_cases`; `models.py` never imports `fastapi`, `pydantic`,
  `schemas`; `schemas.py` never imports `sqlalchemy`, `repository`, `use_cases` or `datetime`.
- `.commit()` / `.rollback()` exist only in `app/db/session.py`; routers never call
  `model_validate` / `model_dump` / `JSONResponse`; domain code raises only `AppError`.
- `app/core/cognito.py` and `app/core/mail.py` are shared infrastructure (auth and users both need
  Cognito; any domain may send mail) — that is why they are not inside `auth/`.

## Conventions

- **Schemas**: `*In` inherits `BaseSchema`, `*Out` inherits `BaseSchemaOut` (`app/core/schemas.py`);
  `pydantic.BaseModel` is banned by ruff `TID251` — the exemptions are the base file and
  `AccessTokenClaims` (a JWT-claims view, not a boundary schema). Fields are snake_case; the wire
  is camelCase via the alias generator — never hand-write aliases, and never serialize a schema
  yourself: handlers return the ORM model / use-case result and `response_model=*Out` validates
  it from attributes exactly once (returning a schema instance builds it twice). Request strings
  are trimmed (`str_strip_whitespace`); credentials use `VerbatimStr` to opt out; every plain
  `str` input field declares `max_length`. Datetimes on the boundary are `UtcDatetime`, never
  bare `datetime`. Emails use `NormalizedEmail`. `*Out` schemas never carry `password`,
  `cognito_sub` or secrets. Every route has a `response_model` (or 204 + `None`).
  (`tests/guards/test_schemas.py`, `test_routes.py`.)
- **Errors**: `AppError.not_found / auth_failed / forbidden / conflict / bad_request / internal /
  service_unavailable`. Handlers in `app/core/exception_handlers.py` produce `ErrorOut`
  (`{error, code, statusCode, correlationId, details?}`); `code` is `ErrorCode` (`StrEnum` in
  `app/core/exceptions.py`), the closed list the envelope can carry — it is an enum in the OpenAPI
  document, so the frontend's generated `ErrorCode` is the same list, and adding a member is a
  wire change (snapshot + `contract-refresh`). Every route declares the errors it can
  produce with `responses=error_responses(404, 422, ...)` (`app/core/openapi.py`); routers
  declare 401, `app/api.py` adds 500/503 to every domain router. Don't catch exceptions in
  routers; `HTTPException`, `JSONResponse` and `BackgroundTasks` are banned imports
  (`tests/guards/test_openapi.py`).
- **Transactions**: repositories `flush()`; `get_db` commits when the request succeeds and rolls
  back otherwise. `DbDep` uses `Depends(get_db, scope="function")` so the commit happens *before*
  the response is sent — guarded.
- **Dependencies**: `Annotated[T, Depends(fn)]` aliases named `*Dep`; every dependency —
  including pure factories — is `async def` (a sync dependency costs a threadpool hop per
  request). Validate in dependencies (`get_membership` resolves `{organization_id}` and 404s);
  reuse the same path-variable name across routes so dependencies chain; path params are
  `snake_case` ending in `_id`.
- **Logging**: `from app.core.logging_config import get_logger` then `logger = get_logger(__name__)`
  at module top; `logger.info("event name", key=value)`. Only `app/core/logging_config.py` imports
  `structlog` (`TID251`). Never interpolate values into the message (ruff `G`/`LOG`).
  Correlation id and user id are attached automatically.
- **Config**: settings objects, each read only by the code that needs it: `settings`
  (`Settings`: tier, identity, `FRONTEND_URL`, logging, CORS), `aws_settings` (`AwsSettings`:
  static boto3 credentials shared by the AWS adapters) and `cognito_settings`
  (`CognitoSettings`: the pool and its region) in `app/core/config.py`; `db_settings`
  (`DatabaseSettings`) in `app/db/config.py` — so Alembic needs only `DATABASE_URL`. Every env
  var is a field on one of them; `os.environ` and `BaseSettings` outside `config.py` are banned
  imports. `ENVIRONMENT` is a `Literal` (a typo refuses to start); `CORS_ORIGINS` rejects `"*"`.
  `.env.example` must list every field (`tests/guards/test_settings.py`). `mail_settings`
  (`MailSettings`, same module) is the exception by design: a frozen dataclass fixing the SES
  sender and region in code — not a `BaseSettings`, so no env var can override it and it has no
  `.env` lines.
- **Auth**: protected routes take `CurrentUserDep` (the ORM `UserModel`). Organization routes
  take `MembershipDep` (member of the path's organization, else 404) or `ManagerDep` (owner or
  admin, else 403). Every operation not listed in `PUBLIC_OPERATIONS`
  (`tests/guards/test_openapi.py`) must carry the bearer requirement.
- **Models**: inherit `Base, TimestampMixin` (UUID pk, `created_at`, `updated_at`). Tables and
  columns are snake_case and singular; datetimes are `DateTime(timezone=True)` and end in `_at`;
  foreign keys end in `_id` (`_by` for audit columns); every `relationship()` declares `lazy=`
  (`selectin` or `raise` — an implicit lazy load raises under the async session). Let the naming
  convention name indexes/constraints. Any model change ships with its migration in the same
  change (`just migration`, review, `just migrate-check`); migrations never import `app`
  and always implement `downgrade` (`tests/guards/test_db_conventions.py`,
  `test_migrations_static.py`).
- **AWS**: talk to Cognito only through `CognitoClient` (`app/core/cognito.py`) and send mail only
  through `MailClient` (`app/core/mail.py`, SES v2); `boto3` is a banned import elsewhere. Both
  wrappers run every call in `asyncio.to_thread` and translate `ClientError` to `AppError` so
  nothing else knows provider codes.
- **Async**: no blocking calls in async code — ruff `ASYNC` plus bans on `time.sleep`,
  `requests`, sync `Session`/`create_engine`. A sync SDK goes through `asyncio.to_thread`.

## Typing

basedpyright runs in strict mode over `app/` and `tests/` with `reportExplicitAny = "error"`:
**a written `Any` is a build failure.** Prefer typed views over untyped dicts (see
`AccessTokenClaims` wrapping `jwt.decode`'s result). Every `# pyright: ignore[...]` must name its
rule and must be needed. The ignores that exist are library boundaries (`CognitoSettings()` /
`DatabaseSettings()` with env-provided required fields, and boto3's per-service overloads); add
another only with a comment explaining the boundary. `reportUnknown*` stays on globally — if a
library forces a rule off, scope it to that file with a commented header.

## Testing (`tests/`)

- Default to HTTP tests through the `client` fixture; assert the response **and** the database
  side-effect; put the happy path and the likeliest failures of one resource in one test class.
- **Every API operation must be requested by at least one test**: the `client` fixture records
  the endpoint that served each request and `pytest_sessionfinish` fails a full green run
  (`just test`, CI) listing any operation never hit. Partial runs (`-k`, a single file) skip
  the check. Every domain with a `router.py` has `tests/<domain>/test_<domain>_router.py`.
- `authenticate_as(user)` bypasses JWT verification; `cognito` is an in-memory `FakeCognitoClient`
  that raises the same `AppError`s as the boto3 implementation, and `mail` a `FakeMailClient` that
  records what would have been sent. Never touch the network;
  `TestClient` and `async_asgi_testclient` are banned imports.
- Seed with `tests/seeds.py` helpers (async, session first, flush, return the model). Rows seeded
  before the request behave like committed data: a failing request rolls back only its own work.
- Real Postgres from `docker compose` (`acme_test`); the schema is rebuilt from `Base.metadata`
  when the `engine` fixture is first used; each test runs in a rolled-back transaction. Suite
  runs serially. `tests/guards/` never requests `engine`, so `just guards` needs no Docker.
- Deprecated pydantic/SQLAlchemy APIs are errors (`filterwarnings`), so v1-style `json_encoders`,
  `.dict()` or `class Config` fail the suite.
- Don't write framework tests (bare "missing field → 422"). The guards are the exception: they
  pin the conventions, not the framework.
- `tests/guards/`: `test_architecture.py` (imports, layout, naming, raises), `test_use_cases.py`,
  `test_routes.py` (async endpoints and dependencies, `*Out` response models, REST naming,
  `DbDep` scope), `test_openapi.py` (bearer on non-public ops, `ErrorOut` on every documented
  error, required statuses, docs hidden in prod, **`openapi.snapshot.json`** — any wire change
  fails until `just openapi-snapshot` is run and the diff reviewed), `test_schemas.py`,
  `test_settings.py`, `test_db_conventions.py`, `test_migrations_static.py`.
  `tests/db/test_migrations.py` proves `alembic upgrade head` equals the models;
  `tests/core/test_security.py` verifies real RS256 tokens against a stubbed JWKS.

## Quality tooling notes

- **ruff** rule sets: pycodestyle, pyflakes, isort, bugbear (`B008` on: no `= Depends()`
  defaults), comprehensions, pyupgrade, logging (`LOG`/`G`), `ARG`, `RUF`, `ASYNC`, `FAST`
  (`FAST003` off: path params consumed by dependencies look unused), `DTZ`, `BLE` (the two
  probe sites carry a `noqa`), `T20`, `N`, `PT`, `S` (tests may `assert` and hold literal
  credentials), `ERA`, `FIX` (no TODO/FIXME left behind), `PLC0415` (imports at module top — a
  lazy import can hide a cycle from sentrux), `TID` (bans + no relative imports). The `TID251`
  ban list in `pyproject.toml` names the sanctioned alternative in each message; the only
  line-level `# noqa: TID251` sites are the two config modules (`BaseSettings`),
  `core/security.py` (`BaseModel` for claims), `core/cognito.py` and `core/mail.py` (boto3),
  `core/exception_handlers.py` (`JSONResponse`, starlette `HTTPException`) and
  `tests/db/test_migrations.py` (sync `create_engine` for Alembic); file-wide only
  `core/schemas.py`, `core/logging_config.py` and `tests/conftest.py`.
- **vulture** runs at 60% confidence on `app/` excluding `schemas.py` / `models.py` (field
  declarations look unused to it). A genuinely unused function or method fails `just check` —
  delete it rather than whitelisting. Names read only via serialization or from outside `app/`
  go in `[tool.vulture].ignore_names` with a comment.
- **deptry**: `uvicorn` and `psycopg` are declared-but-unimported by design (DEP002 ignores).
- **sentrux** is the PyPI release (0.1.x), older than the brew binary. Its `max_cc` is summed per
  file and `max_fn_lines` is file lines ÷ function count; see `app/.sentrux/rules.toml`. Cycles
  are locked at zero and it counts lazy/`TYPE_CHECKING` imports, so don't hide a cycle behind a
  deferred import — invert the dependency instead.
- **Gates**: pre-commit (repo root) runs ruff, basedpyright, vulture, deptry, sentrux,
  `uv lock --check` and `tests/guards` on every commit; `.github/workflows/backend.yml` runs
  `just ci` (everything plus the full suite against Postgres) on pushes to `main` and PRs.
  `.github/workflows/frontend.yml` also runs when `tests/guards/openapi.snapshot.json` changes, so
  a snapshot without the frontend refresh fails CI (`docs/api-contract.md`).

## Adding a domain

1. `app/<name>/` with `__init__.py`, `models.py`, `schemas.py`, `repository.py`, `dependencies.py`,
   `router.py`, `use_cases/`. Models register themselves (the registry walks `app.*.models`);
   the guards discover the domain from the directory.
2. Include the router in `app/api.py`. Declare `responses=error_responses(...)` per route (401 on
   the router when it is protected).
3. `just migration "<name> tables"`, review, `just migrate`, `just migrate-check`.
4. `tests/<name>/test_<name>_router.py` with seeds and a test per operation.
5. `just openapi-snapshot`, then `just contract-refresh` in `frontend/` (`docs/api-contract.md`),
   then `just check && just test` — the guards name anything missing.
