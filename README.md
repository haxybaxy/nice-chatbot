# Acme

Full-stack boilerplate for an app on AWS. Every convention is enforced by a gate (ruff bans,
`tests/guards`, eslint + fallow, pre-commit, CI), not just documented.

- `backend/` — FastAPI · async SQLAlchemy 2 · Alembic · structlog. Auth is backend-proxied AWS
  Cognito (`/api/auth/*`); password-reset mail goes out through SES. Python 3.13, uv. See
  `backend/README.md`.
- `frontend/` — React 19 + Vite SPA (TanStack Query + Form, zod, axios, Tailwind 4, shadcn) whose
  wire types are generated from the backend's guarded OpenAPI snapshot. See `frontend/README.md`.
- `infra/` — OpenTofu for AWS: one Cognito user pool per environment plus the backend's IAM
  policy, state in S3. See `infra/README.md`.
- `docs/` — `api-contract.md`: the backend → frontend type chain and its gates.
- `.github/workflows/` — CI per subproject (`just ci`); `.pre-commit-config.yaml` runs the same
  gates on every commit (`uv run --project backend pre-commit install`).

`CLAUDE.md` (root and per subproject) is the contributor guide, for humans and agents alike.

## Make it yours

Everything project-specific is a placeholder:

| Placeholder    | Stands for          | Used as                                                                                  |
| -------------- | ------------------- | ---------------------------------------------------------------------------------------- |
| `acme`         | project slug        | database names, Docker Compose project, Python package, AWS resource prefix, `AWS_PROFILE` |
| `Acme`         | display name        | API title, SES sender name, page title and app header                                    |
| `example.com`  | your sending domain | the SES identity mail leaves from (`noreply@example.com`); must be verified in SES       |
| `123456789012` | your AWS account id | the OpenTofu state bucket name in `infra/environments/develop/versions.tf`               |

Replace them from the repo root in one pass (`perl` so the command is the same on macOS and Linux):

```bash
git grep -l -E 'acme|Acme' | xargs perl -pi -e 's/acme/<slug>/g; s/Acme/<Name>/g'
git grep -l 'example\.com' -- backend/app backend/README.md backend/.env.example infra \
  | xargs perl -pi -e 's/example\.com/<your-domain>/g'
```

The `@example.com` addresses under `backend/tests` and `frontend/src` are test fixtures; leave
them. Then:

1. `cd backend && uv lock && just check` — refreshes the package name in `uv.lock` and reruns
   every gate. The OpenAPI snapshot already carries the new title, so the guard stays green.
2. `cd frontend && just contract-check && just check` — the vendored spec and generated types
   must still match the backend snapshot.
3. `cd infra && just bootstrap`, paste the printed bucket name into
   `environments/develop/versions.tf`, then `just init && just plan`.
4. Replace `frontend/public/favicon.svg`. If your region is not `us-west-1`, change it in
   `infra/`, `backend/.env.example` and `MailSettings` (`backend/app/core/config.py`).
5. Delete this section.

## Run everything

Each subproject is self-contained (own tooling, dependencies, lockfile — `cd` in for everything
but the stack; first-time setup is in `backend/README.md` and `frontend/README.md`). Once both are
set up, the root `justfile` runs the whole stack:

```bash
just dev        # Postgres (Docker) + migrations, then the API on :8000 and the SPA on :3000 in one terminal
just mprocs     # the same, one mprocs pane per process (api, web, db logs) — `brew install mprocs`
just db-down    # stop Postgres (data is kept)
```
