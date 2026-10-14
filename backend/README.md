# Acme Backend

FastAPI · async SQLAlchemy 2 · Alembic · AWS Cognito · structlog. Python 3.13, managed with uv.
Conventions for contributors (human or agent) are in `CLAUDE.md`; this file is the quick start.

## Quick start

```bash
cp .env.example .env      # local database values work as-is; COGNITO_* only matter for real sign-in
just db-up                # Postgres 18 in Docker, creates the `acme` and `acme_test` databases
uv sync                   # runtime + dev dependencies into .venv
just migrate              # alembic upgrade head
just dev                  # http://localhost:8000 — Swagger UI at /docs (local/develop tiers only)
```

```bash
just check                # ruff · basedpyright (strict, no `Any`) · vulture · deptry · sentrux · uv lock --check · guards
just guards               # convention guards only (tests/guards): architecture, routes, OpenAPI, schemas, settings, DB — no Docker
just test                 # pytest against acme_test; no network, Cognito and SES replaced by in-memory fakes
just cov                  # same, with a coverage report
just                      # every recipe
```

Pre-commit hooks at the repo root run the whole `just check` gate (ruff, basedpyright, vulture,
deptry, sentrux, `uv lock --check`, `tests/guards`): `uv run --project backend pre-commit install`.
CI (`.github/workflows/backend.yml`) runs `just ci` — the same plus the full suite on Postgres —
for pushes to `main` and pull requests. The full suite also fails if any API operation has no
test, and if the OpenAPI document changed without `just openapi-snapshot`. The frontend workflow
(`.github/workflows/frontend.yml`) fails if `frontend/`'s copy of that snapshot was not refreshed
(`just contract-refresh` there; the whole chain is in `docs/api-contract.md`).

## Layout

```
app/
├── main.py             app factory: logging, CORS, request middleware, routers, error handlers, lifespan
├── api.py              router composition + GET /api/health, GET /api/health/ready
├── core/               config (pydantic-settings), errors + JSON envelope, structlog, request middleware,
│                       Cognito + SES mail adapters, JWT verification / CurrentUserDep, shared schema bases
├── db/                 declarative Base + TimestampMixin, engine + get_db, model registry, migrations/
├── auth/               POST /api/auth/{signup,signin,refresh,signout,forgot-password,reset-password}
├── users/              GET/PATCH/DELETE /api/users/me
├── organizations/      POST/GET /api/organizations, GET/POST/DELETE …/members
└── teams/              no routes yet: CreateTeam, called by sign-up for the default team
```

Each domain is flat: `router.py`, `schemas.py`, `models.py`, `repository.py`, `dependencies.py` and
one class per file under `use_cases/`. The layout, import directions and naming are checked by
`tests/guards/` (see `CLAUDE.md`).

## Authentication

Sign-up and sign-in are proxied to Cognito through the admin API; the backend never sees or
stores passwords beyond the request.

1. `POST /api/auth/signup` `{email, password, fullName?}` — creates the Cognito user (email
   pre-verified, permanent password), the local `user` row, the user's personal organization
   (`"<full name>'s organization"`, they are its `owner`) and its default `General` team — all in
   one transaction — then signs in. Returns `{user, organization, team, tokens}`. If any local
   step fails the Cognito user is deleted again.
2. `POST /api/auth/signin` `{email, password}` — returns
   `{accessToken, refreshToken, expiresIn, tokenType}`.
3. Send `Authorization: Bearer <accessToken>` on protected routes. The token is verified locally
   against the pool's JWKS (RS256, issuer, expiry, `token_use=access`, app `client_id`) and its
   `sub` is resolved to the local user.
4. `POST /api/auth/refresh` `{refreshToken}` and `POST /api/auth/signout` (revokes all sessions).
5. `POST /api/auth/forgot-password` `{email}` — always 204. If the address has an account, a
   single-use link (`FRONTEND_URL/auth/reset-password?token=…`, valid 30 minutes) is mailed from
   `noreply@example.com` through SES; only the token's SHA-256 is stored, and a new request
   replaces the previous link.
6. `POST /api/auth/reset-password` `{token, password}` — 204: sets the password in Cognito,
   revokes every session of the user and consumes the link; 400 for an unknown, expired or used
   token, or a password the pool's policy rejects.

### Cognito prerequisites

`infra/` provisions a pool that satisfies all of this (`just apply` there, then `just backend-env`
prints the three `.env` lines). By hand you need:

- A user pool that uses **email as the username**.
- A **public app client** (no secret) with `ALLOW_ADMIN_USER_PASSWORD_AUTH` and
  `ALLOW_REFRESH_TOKEN_AUTH` enabled. A confidential client works for the username-keyed calls
  (`SECRET_HASH` is computed when `COGNITO_CLIENT_SECRET` is set) but not for refresh.
- AWS credentials allowed to call `cognito-idp:AdminCreateUser`, `AdminSetUserPassword`,
  `AdminDeleteUser`, `AdminInitiateAuth` and `AdminUserGlobalSignOut` on the pool
  (`GlobalSignOut` is authorized by the user's access token, not IAM), and `ses:SendEmail` on
  the SES identity the reset mail is sent from (`infra/` grants both). `AWS_ACCESS_KEY_ID` /
  `AWS_SECRET_ACCESS_KEY` in `.env` are passed to boto3 by both adapters when set; otherwise
  boto3 uses its default chain from the **process** environment (the `default` profile, or
  `AWS_PROFILE`; `awscrt` is a dev dependency so `aws login` session profiles resolve too).

Set `AWS_REGION`, `COGNITO_USER_POOL_ID` and `COGNITO_CLIENT_ID` in `.env`; `FRONTEND_URL` is
where the reset links point (default `http://localhost:3000`).

### Mail prerequisites

Password-reset mail goes out through SES v2 from `Acme <noreply@example.com>`. The sender and the
SES region (`us-west-1`, where the sending identity must be verified) are fixed in code —
`MailSettings` in `app/core/config.py` — on purpose: there are no mail variables in `.env`. While
the AWS account is still in the SES sandbox, SES accepts only verified recipients (an address at
the verified sending domain, or an individually verified address); a forgot-password request for
any other existing account then fails with 500 (`MessageRejected` in the logs). Request production
access in the SES console (us-west-1) before real users depend on the flow.

## Errors

Every error — application, validation, unmatched route, database — has one shape:

```json
{"error": "Organization 'b3…' not found", "code": "NOT_FOUND", "statusCode": 404, "correlationId": "7ca4…"}
```

`details` is added in debug tiers (`ENVIRONMENT=local|test|develop|staging`). The
`correlationId` also comes back as the `X-Correlation-ID` response header and is on every log
line of the request; send your own as `X-Request-ID` (a UUID) to have it honoured. The envelope
is the `ErrorOut` schema in the OpenAPI document, and every operation lists the error statuses it
can return.

## Database

- `just migration "add widget table"` autogenerates a revision from the models; review it, then
  `just migrate`. `just migrate-check` fails if models and migrations have drifted.
- Migrations run inside a Postgres advisory lock, so concurrent deploys serialize.
- The container entrypoint runs `alembic upgrade head` unless `RUN_MIGRATIONS=false`.

## Container

```bash
docker build -t acme-backend .
docker run --rm -p 8000:8000 --env-file .env \
  -e DATABASE_URL=postgresql+psycopg://postgres:postgres@host.docker.internal:5432/acme acme-backend
```

## Known gaps

- If the request transaction fails to commit *after* sign-up returned (e.g. the database drops
  mid-request), the Cognito user is left without a local row. Sign-in then fails with 401
  "Unknown user"; delete the Cognito user to let them retry.
- `PATCH /api/users/me` cannot clear a name (`null` means "unchanged").
- Deleting the owner's account (`DELETE /api/users/me`) leaves their organizations without an
  owner; memberships cascade but ownership is not transferred.
- No MFA or email change flows, and no invitation emails — `POST …/members` adds users who
  already have an account.
- `POST /api/auth/forgot-password` answers faster for an unknown address (no mail is sent), so
  timing can still hint at whether an account exists; there is no per-address rate limit yet.
