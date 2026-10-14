# Acme Frontend

React 19 · Vite 8 · TypeScript 5 · TanStack Query 5 · axios · Tailwind CSS 4 · shadcn/ui (Radix).
Conventions for contributors (human or agent) are in `CLAUDE.md`; this file is the quick start.

## Quick start

```bash
cp .env.example .env      # empty VITE_API_BASE_URL → http://localhost:8000 (the backend's `just dev`)
npm ci                    # Node ≥ 22.22 (jsdom); npm, lockfile committed
just dev                  # http://localhost:3000 — the one origin the backend allows by default
```

```bash
just check                # prettier · eslint (0 warnings) · tsc --noEmit · knip · jscpd · madge · fallow
just test                 # vitest once, against MSW + the backend contract validator; `just test -t "refresh"`
just cov                  # same, with a coverage report (reporting only, no threshold)
just contract-refresh     # after any backend API change: backend snapshot → openapi.json → schema.d.ts (commit all three)
just contract-check       # drift check of that chain (pre-commit and CI run it too)
just build                # production bundle in dist/
just                      # every recipe
```

Pre-commit hooks (prettier, eslint, tsc, fallow, contract check) are configured at the repo root:
`uv run --project backend pre-commit install`. CI (`.github/workflows/frontend.yml`) runs `just ci`
for pushes to `main` and pull requests.

## Layout

```
src/
├── main.tsx            StrictMode → ErrorBoundary → BrowserRouter → Providers → App
├── App.tsx             routes: /auth/{login,sign-up} (guest only) · /app (protected) · * → login
├── globals.css         Tailwind 4 + shadcn tokens (oklch), light/dark via the `.dark` class
├── layouts/            AuthLayout (centered card), ProtectedLayout (header + ProtectedRoute gate)
├── providers/          QueryProvider → AuthProvider → ThemeProvider (+ AppToaster); `use-*.ts` hooks
├── shared/
│   ├── api/            `Schema<"UserOut">` over generated/schema.d.ts (from the OpenAPI snapshot)
│   ├── config/         api-endpoints.ts — every path the app calls
│   ├── constants/      app (APP_NAME), routes, query-keys, storage-keys
│   ├── services/       api-client (axios + bearer + 401 refresh), auth-bridge, token-storage, refresh-error, local-storage
│   ├── utils/          cn()
│   └── components/     ui/ (shadcn), feedback/ (Spinner, Loading), error-boundary/
├── features/
│   ├── auth/           components · hooks · pages · schemas · services · types · __tests__
│   └── home/           the signed-in landing page
└── test/               vitest setup, MSW server/handlers/fixtures (`mockApi`), contract validator + openapi.json, guards/
```

Each feature is self-contained and exposes its public API through `index.ts`.

## Authentication

Email + password against our own backend (`/api/auth/*`, which proxies AWS Cognito). No
Hosted UI, no redirects.

- `POST /api/auth/signup` creates the account and signs in; `POST /api/auth/signin` returns
  `{accessToken, refreshToken, expiresIn, tokenType}`.
- The **access token lives in memory**; the **refresh token lives in localStorage**. On every
  app load `AuthProvider` restores the session: refresh token → `POST /api/auth/refresh` →
  `GET /api/users/me`. That is what keeps you signed in across reloads (for up to the pool's
  30-day refresh-token lifetime).
- `apiClient` attaches the bearer token, and on a 401 refreshes once (concurrent requests
  share the refresh) and retries. A rejected refresh ends the session; a network blip does not.
- `POST /api/auth/signout` revokes every refresh token server-side; the local pair is cleared
  even if that call fails.

## Backend contract

`src/test/contract/openapi.json` is a byte copy of the backend's guarded OpenAPI snapshot
(`backend/tests/guards/openapi.snapshot.json`) and `src/shared/api/generated/schema.d.ts` the
TypeScript types generated from it. `apiClient` is typed by path + verb from those types, so a
request body or response shape the backend doesn't declare is a compile error. After any backend
API change run `just contract-refresh` (snapshots the backend, copies, regenerates — no server
needed) and commit the three files together; `just contract-check`, pre-commit and CI fail on
drift. In tests, every request body, query string and mocked 2xx response is also validated
against the snapshot at runtime. The whole process: `docs/api-contract.md`.

## Environment

| Variable            | Default                 | Notes                                             |
| ------------------- | ----------------------- | ------------------------------------------------- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend origin. Keep the dev server on port 3000, |
|                     |                         | or add the new origin to the backend's            |
|                     |                         | `CORS_ORIGINS`.                                   |
