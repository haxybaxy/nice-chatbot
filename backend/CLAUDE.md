# CLAUDE.md — backend

Guidance for working in `backend/`. `README.md` has the quick start; this file has the rules.
Most rules here are **enforced**: ruff (`pyproject.toml`), basedpyright, the guard tests in
`tests/guards/` (DB-free, run by pre-commit on every commit) and the full suite in CI. When a
gate fails, fix the code to match the convention; do not loosen the gate.

## Commands (run from `backend/`)

```bash
uv sync                          # install
just dev                         # uvicorn with reload on :8000
just worker                      # the chat run worker with reload (python -m app.worker)
just check                       # fmt + lint + typecheck + deadcode + deps + audit + lock-check + guards — before every commit
just guards                      # tests/guards only (architecture, routes, OpenAPI, schemas, settings, DB, migrations) — no Docker
just test                        # pytest (needs `just db-up`); `just test -k signup` for a subset
uv run pytest tests/auth/test_auth_router.py::TestSignUp -q      # one file / class / test
just openapi-snapshot            # after an intentional API change: rewrite tests/guards/openapi.snapshot.json, then `just contract-refresh` in frontend/
just migration "msg" && just migrate && just migrate-check
```

Python 3.13 · uv · FastAPI · async SQLAlchemy 2 (`postgresql+psycopg`) · Alembic · pydantic v2 ·
structlog · pyjwt · boto3 (Cognito, SES) · LangGraph + LangChain (`langchain-anthropic`,
`langchain-openai`) · Langfuse · httpx (Tavily) · pypdf + python-docx (attachment text extraction) ·
python-multipart (uploads). Chat runs execute in a second process, the worker
(`app/worker.py`), fed by a Postgres queue — `docs/chat-architecture.md` has the flow. Follows
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
└── use_cases/         one class per file: __init__(<DI seams>) + async execute(*, ...)
```

A domain directory contains exactly these entries (guard: no `service.py`, `utils.py`, …).
`app/core` (config, errors, logging, middleware, Cognito and SES mail adapters, JWT security,
schema bases, OpenAPI helpers, the SSE response, the attachment download response (`downloads.py`),
the AI SDK chunk vocabulary in `ui_stream.py` / `ui_fold.py`, and the chat runtime: `llm/` (catalog +
LangChain model builder + history, with `llm/attachments.py` rendering attachments for the model),
`tools/`, `agent/`
(the LangGraph graph, stream mapper, checkpointer, and the worker's turn sink / mode assembly), `research/`, `search.py`, `sandbox.py`,
`observability.py`, `prompts.py`), `app/db` (Base, engine, `get_db` + `session_scope`, the
LISTEN/NOTIFY `listen.py`, model registry, DB settings, migrations), `app/api.py` (router
composition + health), `app/main.py` (app factory), `app/worker.py` (the run worker). Nothing under
`app/` imports `api.py`, `main.py` or `worker.py` (guard).

### Use-case shape

```python
class InviteMember:
    def __init__(self, session: AsyncSession) -> None:
        self._find_user = FindUserByEmail(session)      # compose other use cases by session
        self._members = OrganizationMemberRepository(session)

    async def execute(self, *, actor: OrganizationMemberModel, email: str, role: OrganizationRole) -> OrganizationMemberModel:
        ...                                             # business args keyword-only; return models, never schemas
```

The constructor is the DI seam and takes only the names in `INIT_PARAMS`
(`tests/guards/test_use_cases.py`): `session` (the request transaction), `sessions` (a
`SessionScope` factory, for use cases that outlive one transaction — the worker loop, the SSE
tail — each opening a short `session_scope()` per database step), and the adapters `cognito`,
`mail`, `llm` (chat-model factory), `tools` (tool registry), `tracer`, `checkpointer`, `listener`,
`search`, `sandbox`; `execute` is the single public method and carries only keyword business
arguments; raise `AppError.<factory>()` on rule violations. A result that spans several objects is a frozen `@dataclass` next to the use
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
- `.commit()` / `.rollback()` exist only in `app/db/session.py` (`get_db` for requests,
  `session_scope()` for everything else); routers never call `model_validate` / `model_dump` /
  `JSONResponse`; domain code raises only `AppError`.
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
  the response is sent — guarded. Code that outlives a request (the worker, an SSE tail) never
  holds a transaction across a network `await`: it opens `session_scope()` per step. A
  `StreamingResponse` body runs after the request session is closed, so it uses `sessions` too.
- **Streaming**: the run event stream (`GET …/runs/{run_id}/events`) is an
  `UIMessageStreamResponse` (`app/core/sse.py`) replaying `run_event` rows as AI SDK UI chunks
  (`app/core/ui_stream.py`) with `id: <seq>` frames, then tailing `LISTEN run_events` through
  `PgListener` (`app/db/listen.py`, a dedicated autocommit psycopg connection, never the pool).
  The other non-JSON route is the attachment download (`GET /api/attachments/{attachment_id}/content`),
  an `AttachmentContentResponse` (`app/core/downloads.py`, class `media_type`
  `application/octet-stream`, the stored type per instance). `tests/guards/test_routes.py` exempts
  `StreamingResponse` subclasses whose class `media_type` is `text/event-stream` or
  `application/octet-stream` from the `response_model` rule; error responses are still the JSON
  envelope (`json_error_envelopes` in `app/core/openapi.py` rewrites both media types).
- **Attachments** (`app/attachments/`): an upload (`POST /api/teams/{team_id}/attachments`, multipart
  field `file`, read in 64 KiB chunks and refused past `ATTACHMENT_MAX_BYTES`) becomes an
  `attachment` row (metadata, `kind` ∈ `image|pdf|docx|text` from the declared type with an
  extension fallback, the canonical `media_type`) plus an `attachment_blob` row — the bytes live in
  their own table so listing never loads them, and `AttachmentRepository.put_blob` / `get_blob` is
  the seam an S3 adapter would replace. Text is extracted **at upload time** (`ExtractText`: pypdf,
  python-docx, UTF-8; run in `asyncio.to_thread`; a corrupt or encrypted file sets
  `extraction_error` instead of failing the upload), never by the worker. An upload belongs to its
  uploader until a message is created with a `{"type": "file", "attachmentId"}` part:
  `CreateMessage` binds it through the attachments domain's public `ClaimAttachmentsForMessage`
  (same team and uploader else 404, already bound 409, over `ATTACHMENT_MAX_PER_MESSAGE` or
  repeated 400) and persists the AI SDK `file` part (`mediaType`, `filename`, `url`, `attachmentId`).
  `LoadTurn` reads the attachments of the user messages in the history window
  (`LoadMessageAttachments`, image bytes only for images) onto `StoredMessage.attachments`;
  `to_langchain` then builds that user message as content blocks — text first, an
  `<attachment name type chars>` block per text-bearing file under the turn-wide
  `ATTACHMENT_MODEL_TEXT_CHARS` budget (newest first, `[truncated: N more characters]`),
  `<attachment … unreadable/>` for a failed extraction, `create_image_block` for images when
  `ModelSpec.supports_vision` (Claude; OpenAI-compatible via `LLM_OPENAI_SUPPORTS_VISION`) and a
  text placeholder otherwise; messages without attachments stay plain strings. The worker's reaper
  also runs `ReapOrphanAttachments`: uploads with `message_id IS NULL` older than
  `ATTACHMENT_ORPHAN_TTL_HOURS` go (a deleted conversation cascades to its messages, which SET NULL
  the attachments, so they are swept too).
- **Runs**: the `run` row is the queue (claimed with `FOR UPDATE SKIP LOCKED`, heartbeated, reaped),
  `run_event` the ordered chunk log, `LISTEN/NOTIFY` the wake-up (`run_queue`, `run_events`,
  `run_control`). Every worker-side write is fenced by `worker_id` + `status = 'running'`; the
  `(run_id, seq)` unique constraint is the backstop. Persisted `message.parts` mirror the UI message
  shape (`fold_parts`), `provider_messages` keep the turn's LangChain messages verbatim.
  The worker (`app/worker.py`) is one `Worker` over injected collaborators (`WorkerDeps`): a claim
  loop (`ClaimRun` → one `RunAssistantTurn` task per run under `Semaphore(WORKER_CONCURRENCY)`;
  idle → `LISTEN run_queue` bounded by `WORKER_POLL_INTERVAL_S`) plus a reaper task (`ReapStaleRuns`,
  then `ReapOrphanAttachments`, every `WORKER_REAPER_INTERVAL_S`). SIGTERM/SIGINT stop claiming,
  let the reaper finish its pass (a stop interrupts waits, never a database statement — a cancelled
  statement invalidates its connection) and cancel the running turns — each closes its run (parts
  so far persisted, an `error` chunk, `failed` "worker shutting down") within
  `WORKER_SHUTDOWN_GRACE_S` — then the
  tracer, search client, checkpointer pool, listener and engine are shut. `RunAssistantTurn` is
  the unit of work (`LoadTurn` in one scope → `SaveAssistantMessage` + `start{messageId}` →
  `WatchRunLease` heartbeat → the title in the background → the chat or research graph from
  `app/core/agent/turn_graphs.py` under `asyncio.timeout` → `TurnSink` batches + per-step upserts
  → `FinishRun`); `message.parts` is always `fold_parts` of the whole event log, so the stream and
  REST agree. Cancel: `run_control` wakes the heartbeat, the graph stops between chunks, `abort` +
  `cancelled`. A lost lease (reaped, re-queued) ends the turn with no further write. Resume
  (attempt 2): the LangGraph thread continues (`astream(None)`) when it holds a checkpoint,
  `reset-step` is emitted only when the log ends inside a model step (a loss during a tool round
  re-emits the tool outputs onto parts the client already has), sources are re-seeded from the
  persisted `source-url` parts and usage/steps add on top of attempt 1; with no checkpoint
  (`AGENT_CHECKPOINTER=none`) the run starts over.
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
  static boto3 credentials shared by the AWS adapters), `cognito_settings`
  (`CognitoSettings`: the pool and its region), `chat_settings` / `worker_settings` (run limits,
  the worker loop), `attachment_settings` (upload size, per-message count, extraction and per-turn
  text caps, orphan TTL), `llm_settings` / `agent_settings` (providers, the model allowlist, agent
  budgets), `search_settings` / `sandbox_settings` / `research_settings` (tools, deep research)
  and `langfuse_settings` in `app/core/config.py`; `db_settings` (`DatabaseSettings`) in
  `app/db/config.py` — so Alembic needs only `DATABASE_URL`. The chat settings all have defaults
  and a blank value (`KEY=`) means unset: a missing provider key hides its models, a missing search
  key drops the web tools, missing Langfuse keys make tracing a no-op; only inconsistent
  configuration (a default model outside `LLM_MODELS`, `openai:claude-*`) refuses to start. Every env
  var is a field on one of them; `os.environ` and `BaseSettings` outside `config.py` are banned
  imports. `ENVIRONMENT` is a `Literal` (a typo refuses to start); `CORS_ORIGINS` rejects `"*"`.
  `.env.example` must list every field (`tests/guards/test_settings.py`). `mail_settings`
  (`MailSettings`, same module) is the exception by design: a frozen dataclass fixing the SES
  sender and region in code — not a `BaseSettings`, so no env var can override it and it has no
  `.env` lines.
- **Auth**: protected routes take `CurrentUserDep` (the ORM `UserModel`). Organization routes
  take `MembershipDep` (member of the path's organization, else 404) or `ManagerDep` (owner or
  admin, else 403); team routes `TeamMembershipDep` / `TeamManagerDep` (creator or organization
  manager); conversation routes `ConversationAccessDep` (team member and visibility, else 404)
  and `RunAccessDep`; attachment routes `AttachmentAccessDep` (row exists and the caller is a
  member of its team, else 404; the chat and attachments domains each resolve `{team_id}` with
  their own `TeamAccessDep` over `FindTeamMembership`, since a domain never imports another's
  `dependencies`). Every operation not listed in `PUBLIC_OPERATIONS`
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
- Real Postgres from `docker compose` (`nicechatbot_test`); the schema is rebuilt from `Base.metadata`
  when the `engine` fixture is first used; each test runs in a rolled-back transaction. Suite
  runs serially. `tests/guards/` never requests `engine`, so `just guards` needs no Docker.
- Deprecated pydantic/SQLAlchemy APIs are errors (`filterwarnings`), so v1-style `json_encoders`,
  `.dict()` or `class Config` fail the suite.
- Don't write framework tests (bare "missing field → 422"). The guards are the exception: they
  pin the conventions, not the framework.
- Chat tests: router tests drive the SSE route through `client.stream(...)` with the
  `FakeListener` (NOTIFY never fires inside the rolled-back test transaction, so the reader's poll
  fallback is what runs); `tests/db/test_listen.py` is the one place that commits real rows (and
  truncates them) to prove `PgListener` and the `SKIP LOCKED` claim. The chat runtime is tested
  with the fakes in `tests/fakes_llm.py` (a scripted chat model, search, sandbox, tracer) — never a
  provider, never Docker (the sandbox integration test is `@pytest.mark.docker` and skipped
  without a daemon).
- `tests/guards/`: `test_architecture.py` (imports, layout, naming, raises), `test_use_cases.py`,
  `test_routes.py` (async endpoints and dependencies, `*Out` response models except the two byte
  streams, REST naming, `DbDep` scope), `test_openapi.py` (bearer on non-public ops, `ErrorOut` on every documented
  error, required statuses, docs hidden in prod, **`openapi.snapshot.json`** — any wire change
  fails until `just openapi-snapshot` is run and the diff reviewed), `test_schemas.py`,
  `test_settings.py`, `test_db_conventions.py`, `test_migrations_static.py`.
  `tests/db/test_migrations.py` proves `alembic upgrade head` equals the models;
  `tests/core/test_security.py` verifies real RS256 tokens against a stubbed JWKS.

## Quality tooling notes

- **ruff** rule sets: pycodestyle, pyflakes, isort, bugbear (`B008` on: no `= Depends()`
  defaults), comprehensions, pyupgrade, logging (`LOG`/`G`), `ARG`, `RUF`, `ASYNC`, `FAST`
  (`FAST003` off: path params consumed by dependencies look unused), `DTZ`, `BLE` (the two
  probe sites, the worker loops and the attachment text extractor carry a `noqa`), `T20`, `N`,
  `PT`, `S` (tests may `assert` and hold literal
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
- **deptry**: `uvicorn` (CLI entrypoint), `langgraph-checkpoint-postgres` (imported through the `langgraph` namespace) and `python-multipart` (loaded by FastAPI for `UploadFile`) are declared-but-unimported by design (DEP002 ignores); `psycopg` is imported directly by `app/db/listen.py`.
- **sentrux** is the PyPI release (0.1.x), older than the brew binary. Its `max_cc` is summed per
  file and `max_fn_lines` is file lines ÷ function count; see `app/.sentrux/rules.toml`. Cycles
  are locked at zero and it counts lazy/`TYPE_CHECKING` imports, so don't hide a cycle behind a
  deferred import — invert the dependency instead.
- **Gates**: pre-commit (repo root) runs ruff, basedpyright, vulture, deptry, sentrux,
  `uv lock --check` and `tests/guards` on every commit; `.github/workflows/backend.yml` runs
  `just ci` (everything plus the full suite against Postgres) on pushes to `main` and PRs.
  `.github/workflows/frontend.yml` also runs when `tests/guards/openapi.snapshot.json` changes, so
  a snapshot without the frontend refresh fails CI (`docs/api-contract.md`).

## Chat runtime conventions

- Claude is reached only through `ChatAnthropic` built by `build_chat_model`
  (`app/core/llm/models.py`); `ChatOpenAI` serves OpenAI-compatible servers only (`openai:claude-*`
  is rejected by settings). Never import `anthropic`; `openai` only in `app/core/llm/errors.py`;
  `langchain_anthropic` / `langchain_openai` only in `models.py`; `langfuse` only in
  `app/core/observability.py`; `langgraph.checkpoint.postgres` only in `app/core/agent/checkpointer.py`
  (ruff `TID251`).
- Histories are append-only. Same-provider turns replay the stored `provider_messages` verbatim
  (thinking blocks and signatures included); another provider rebuilds text + tool calls from
  `parts` and drops reasoning.
- Everything a run emits is an AI SDK UI chunk (`app/core/ui_stream.py`): the LangGraph stream
  mapper, the tools (through `get_stream_writer()`) and the research graph all speak it; the worker
  persists it (`run_event`) and folds it (`message.parts`). Never route chunks through `BaseSchema`.
- Sources are numbered per run (`SourceRegistry`), cited as `[n]`, and streamed once as
  `source-url` parts. Tools return `(content_for_model, artifact)`; a failing tool is an error
  `ToolMessage`, never a failed run.
- `reportUnknown*` is relaxed per file, with a header naming the library boundary, only in the
  LangChain/LangGraph/Langfuse-facing modules (`llm/models.py`, `llm/history.py`,
  `tools/registry.py`, `agent/graph.py`, `agent/stream.py`, `research/graph.py`,
  `observability.py`, `tests/fakes_llm.py`); `reportExplicitAny` is never relaxed.

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
