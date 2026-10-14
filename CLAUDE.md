# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

Monorepo. Each subproject is self-contained (own tooling, dependencies, lockfile); there is no
root package manager or workspace — `cd` into a subproject before running anything.

This is a boilerplate: `acme` / `Acme` / `example.com` / the AWS account id `123456789012` are
placeholders for the project slug, display name, SES sending domain and account. `README.md` →
"Make it yours" lists where each one lives and how to replace them in one pass.

| Dir | Status | Guide |
|---|---|---|
| `backend/` | FastAPI API | `backend/CLAUDE.md` (authoritative for its conventions; read it before changing backend code) |
| `infra/` | OpenTofu for AWS — one Cognito user pool per environment (`develop` in us-west-1) plus the backend's IAM policy (cognito-idp admin calls, `ses:SendEmail` on the verified SES identity) | `infra/CLAUDE.md` |
| `.github/workflows/` | CI — `backend.yml` runs `just ci` (all gates + full suite on Postgres) for pushes to `main` and PRs touching `backend/`; `frontend.yml` runs the frontend's `just ci` for `frontend/**` and for the backend OpenAPI snapshot | — |
| `frontend/` | React 19 + Vite SPA (TanStack Query, TanStack Form + zod, axios, Tailwind 4, shadcn) | `frontend/CLAUDE.md` (authoritative for its conventions; read it before changing frontend code) |
| `docs/` | `api-contract.md` — the backend → frontend type chain and its gates | — |

Root-level tooling is deliberately thin: a `justfile` + `mprocs.yaml` that only run the whole stack
(`just dev` — Postgres, migrations, API on :8000 and SPA on :3000 in one terminal; `just mprocs` —
the same with one mprocs pane per process), and `.pre-commit-config.yaml`: pre-commit reads its
config from the git root, so subproject hooks live here, scoped with `files:` — backend hooks run through
`uv run --project backend …` / `uv run --directory backend …` (ruff, basedpyright, vulture,
deptry, sentrux, `uv lock --check` and the DB-free convention guards in `backend/tests/guards`),
frontend hooks through `npm --prefix frontend …` (prettier, eslint, tsc, fallow, the contract check — so
`npm ci` in `frontend/` first), the infra hook runs `tofu fmt -check`. Install once with
`uv run --project backend pre-commit install`.

## Cross-subproject contract

The frontend vendors the backend's guarded OpenAPI snapshot and generates its wire types from it;
nothing about the wire is hand-written on either side, and `apiClient` is typed by path + verb.
After any backend API change: `just openapi-snapshot` (in `backend/`), then `just contract-refresh`
(in `frontend/`), and commit the three generated files with the change. `just contract-check`, the
root pre-commit hook and `frontend.yml` fail on any drift; ESLint bans raw `axios`, direct imports
of the generated module and inline `as { … }` casts. Process, gates and failure messages:
`docs/api-contract.md`.

## Backend quick reference (run from `backend/`)

```bash
cp .env.example .env && just db-up && uv sync && just migrate   # first-time setup (Postgres in Docker)
just dev                                                        # uvicorn on :8000, Swagger UI at /docs
just check                                                      # ruff · basedpyright strict · vulture · deptry · sentrux · lock · guards
just guards                                                     # convention guards only (tests/guards) — no Docker needed
just test                                                       # whole suite (needs the compose Postgres); fails if any route lacks a test
just openapi-snapshot                                           # after an intentional API change; then `just contract-refresh` in frontend/
uv run pytest tests/auth/test_auth_router.py::TestSignUp -q     # one file / class / test; or `just test -k <name>`
just migration "msg" && just migrate && just migrate-check      # after any model change, in the same change
```

`just` with no arguments lists every recipe.

## Infra quick reference (run from `infra/`)

```bash
just login [profile]                    # only for an aws-login session profile; static keys in `default` need nothing
just bootstrap                          # one-time: S3 state bucket in us-west-1
just init && just plan && just apply    # develop by default; `just plan <env>` for another
just backend-env                        # AWS_REGION / COGNITO_USER_POOL_ID / COGNITO_CLIENT_ID lines for backend/.env
just check                              # tofu fmt -check + offline validate of every environment
```

## Frontend quick reference (run from `frontend/`)

```bash
cp .env.example .env && npm ci                                  # first-time setup (Node ≥ 22.22)
just dev                                                        # Vite on :3000 (the backend's default CORS origin), talks to :8000
just check                                                      # prettier · eslint · tsc · knip · jscpd · madge · fallow (dead code · dupes · complexity · boundaries)
just test                                                       # vitest once (MSW + contract validator); `just test -t "refresh"` for a subset
just contract-refresh                                           # after any backend API change: backend snapshot → openapi.json → schema.d.ts (commit all three)
just contract-check                                             # non-mutating drift check of that chain (also pre-commit + CI)
just ui-add dialog select                                       # add shadcn components
```

## Backend architecture in one screen

- `app/` is package-by-feature: `auth`, `users`, `organizations`, `teams`, each with `router` /
  `schemas` / `models` / `repository` / `dependencies` and one class per file under `use_cases/`
  (`__init__(session[, cognito])` + `async execute(*, ...)`; use cases return ORM models, routers
  return them and `response_model=*Out` serializes). `teams` has no routes yet — models, repository
  and `CreateTeam` only. `app/core` holds settings (`Settings`, `AwsSettings`, `CognitoSettings` and the code-fixed
  `MailSettings`), `AppError` and the single JSON error envelope (`ErrorOut`, declared on routes
  via `error_responses`), structlog with correlation ids, the request middleware, the Cognito and
  SES mail adapters and JWT security; `app/db`
  holds the declarative base, engine, `get_db`, `DatabaseSettings` and Alembic. `app/api.py` and
  `app/main.py` are composition roots that nothing else imports. These rules are enforced by
  `backend/tests/guards/` and ruff bans, not just documented.
- A request commits through `get_db` (`Depends(get_db, scope="function")`, so the commit happens
  before the response is sent); repositories only `flush()`. A domain may import another domain's
  `models` and `use_cases`, never its `repository`, `schemas`, `router` or `dependencies` —
  `tests/guards/test_architecture.py` enforces this.
- Auth is backend-proxied AWS Cognito: `/api/auth/*` call cognito-idp via boto3 behind the
  `CognitoClient` Protocol in `app/core/cognito.py`; protected routes verify the bearer access token
  against the pool's JWKS and resolve its `sub` to the local `user` row (`CurrentUserDep`).
  Sign-up also creates the user's personal organization (they are its `owner`) and a default
  `General` team, in the same transaction as the `user` row. Organization routes are gated by
  `MembershipDep` / `ManagerDep`. Password reset is backend-owned: `POST /api/auth/forgot-password`
  mails a single-use 30-minute link (SES v2 behind the `MailClient` Protocol in `app/core/mail.py`,
  sender fixed in `MailSettings`) and `POST /api/auth/reset-password` sets the password through
  Cognito and revokes the user's sessions.
- basedpyright runs strict with written `Any` banned; the wire format is camelCase generated from
  snake_case schema fields; datetimes on the boundary are `UtcDatetime`.
- Tests hit the compose Postgres (`acme_test`) inside rolled-back transactions with in-memory
  Cognito and mail fakes — never the network.
