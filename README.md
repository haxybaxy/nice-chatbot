# Nice Chatbot

Full-stack boilerplate for an app on AWS. Every convention is enforced by a gate (ruff bans,
`tests/guards`, eslint + fallow, pre-commit, CI), not just documented.

- `backend/` — FastAPI · async SQLAlchemy 2 · Alembic · structlog. Auth is backend-proxied AWS
  Cognito (`/api/auth/*`); password-reset mail goes out through SES. Team-scoped chat runs on a
  LangGraph worker (`python -m app.worker`) with web search, deep research and a code sandbox,
  streamed as the AI SDK UI Message Stream and traced with Langfuse. Python 3.13, uv. See
  `backend/README.md` and `docs/chat-architecture.md`.
- `frontend/` — React 19 + Vite SPA (TanStack Query + Form, zod, axios, Tailwind 4, shadcn) whose
  wire types are generated from the backend's guarded OpenAPI snapshot. See `frontend/README.md`.
- `infra/` — OpenTofu for AWS: one Cognito user pool per environment plus the backend's IAM
  policy, state in S3. See `infra/README.md`.
- `docs/` — `api-contract.md` (the backend → frontend type chain and its gates),
  `chat-architecture.md` (request → queue → worker → graph → SSE), `adr/` (decisions).
- `.github/workflows/` — CI per subproject (`just ci`); `.pre-commit-config.yaml` runs the same
  gates on every commit (`uv run --project backend pre-commit install`).

`CLAUDE.md` (root and per subproject) is the contributor guide, for humans and agents alike.

## Make it yours

Everything project-specific is a placeholder:

| Placeholder    | Stands for          | Used as                                                                                  |
| -------------- | ------------------- | ---------------------------------------------------------------------------------------- |
| `nicechatbot`         | project slug        | database names, Docker Compose project, Python package, AWS resource prefix, `AWS_PROFILE` |
| `Nice Chatbot`         | display name        | API title, SES sender name, page title and app header                                    |
| `example.com`  | your sending domain | the SES identity mail leaves from (`noreply@example.com`); must be verified in SES       |
| `123456789012` | your AWS account id | the OpenTofu state bucket name in `infra/environments/develop/versions.tf`               |

Replace them from the repo root in one pass (`perl` so the command is the same on macOS and Linux):

```bash
git grep -l -E 'nicechatbot|Nice Chatbot' | xargs perl -pi -e 's/nicechatbot/<slug>/g; s/Nice Chatbot/<Name>/g'
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
just dev        # Postgres (Docker) + migrations, then the API on :8000, the chat worker and the SPA on :3000
just mprocs     # the same, one mprocs pane per process (api, worker, web, db logs) — `brew install mprocs`
just db-down    # stop Postgres (data is kept)
```

Environment variables are for secrets; everything else has a code default. In `backend/.env` set
`ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` (each key activates its provider's models in the
picker; the first available model becomes the default), `TAVILY_API_KEY` for web search,
`SANDBOX_BACKEND=docker` (after `just sandbox-pull` in `backend/`) for code execution, and
`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` for tracing. Everything degrades gracefully when
unset: that provider's models, that tool or tracing simply disappear. A local OpenAI-compatible
server (vLLM, Ollama, unsloth) is the one non-secret override: `OPENAI_BASE_URL` plus its models
in `LLM_MODELS`. The containerized backend
(API + worker) is `docker compose --profile app up --build` in `backend/`.
