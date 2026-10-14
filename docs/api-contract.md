# The backend → frontend API contract

Every type the frontend uses for the wire is generated from the backend's Pydantic schemas.
Nobody hand-writes a wire shape — a human or an agent regenerates. Each link of the chain has a
gate; this page says which, what to run, and what each failure means.

## The chain

```
Pydantic *In / *Out  (backend/app/*/schemas.py, app/core/schemas.py)
  │  app.openapi()
  ▼
backend/tests/guards/openapi.snapshot.json      written by: just openapi-snapshot   (backend/)
  │  byte copy                                  guard:  test_openapi_snapshot_is_current
  ▼                                                     (just guards · pre-commit · backend.yml)
frontend/src/test/contract/openapi.json         written by: just contract-refresh   (frontend/)
  │  openapi-typescript 7.13.0 (exact-pinned)   guard:  contract-check (a)
  ▼                                                     (just check · pre-commit · frontend.yml)
frontend/src/shared/api/generated/schema.d.ts   guard:  contract-check (b)
  │
  ▼
frontend/src/shared/api/types.ts                Schema<"UserOut"> · ApiPath · RequestBody<…> · SuccessBody<…>
  ├─ src/shared/config/api-endpoints.ts         every path, `satisfies Record<string, ApiPath>`
  ├─ src/shared/services/api-client.ts          path-typed: apiClient.post(path, body) — no <T>
  ├─ src/features/*/types/index.ts              aliases: export type UserProfile = Schema<"UserOut">
  └─ src/test/msw/typed-http.ts                 mockApi.<verb>(path, resolver) — spec-typed handlers
```

`just contract-refresh` (run in `frontend/`) walks the first three links in one command; both
scripts live in `frontend/scripts/`. The vendored spec is a byte copy of the backend's guarded
snapshot — there is exactly one serialization of the OpenAPI document, so the two files can only
differ when the refresh was not run.

## When you change the backend API

Any change to a schema, a route, a `response_model`, a query parameter or an error declaration:

```bash
cd backend
just openapi-snapshot && just check     # rewrite the snapshot; review its diff
cd ../frontend
just contract-refresh                   # backend snapshot → openapi.json → schema.d.ts
just check && just test                 # tsc names the read sites; the validator names the mocks
```

Commit the three generated files **with** the backend change:

- `backend/tests/guards/openapi.snapshot.json`
- `frontend/src/test/contract/openapi.json`
- `frontend/src/shared/api/generated/schema.d.ts`

(`just contract-refresh` runs the backend step again; that is harmless.) Expect type errors where
the frontend reads a field you renamed or removed — fix the reader. Expect runtime contract
violations where a mock returns a shape the backend no longer produces — fix the fixture or the
handler. Never the snapshot.

## When you add a frontend call

1. Add the path to `API_ENDPOINTS` (`src/shared/config/api-endpoints.ts`). It must be a path the
   spec declares; a typo is a compile error.
2. Call it from the feature's service: `apiClient.get(API_ENDPOINTS.USERS.ME)`,
   `apiClient.post(API_ENDPOINTS.AUTH.SIGNIN, body, { skipAuth: true })`. There is no type
   parameter — the path + verb decide the body and the result. Templated paths take their
   segments through `options.path`
   (`apiClient.get("/api/organizations/{organization_id}", { path: { organization_id } })`);
   query parameters through `options.query`. A verb without a body is `apiClient.post(path)`; to
   pass options to it write `apiClient.post(path, undefined, { skipAuth: true })`.
3. Alias the schemas the feature reads in `features/<name>/types/index.ts`:
   `export type Organization = Schema<"OrganizationOut">`. One alias per schema; two endpoints
   that return different schemas get two aliases.
4. Mock it with `mockApi.<verb>(API_ENDPOINTS…, resolver)` (`src/test/msw/typed-http.ts`):
   `request.json()` is the `*In` schema, `params` are the path's segments, and the response must
   be the `*Out` schema or `errorResponse(status, code)` (`src/test/msw/fixtures/error.ts`).
   Build bodies with the `make*()` fixtures.
5. `just check && just test`.

Hand-written declarations remain legitimate in exactly two cases, always commented with what they
are: a client-only shape that never hits the wire (`SessionUser`, a cache state) and a named
structural probe on an error object (`shared/services/refresh-error.ts`). A hand-written type that *narrows* a
wire request (an invariant OpenAPI cannot express) must be anchored to its schema with a
conformance alias — `type Narrows<Wire, T extends Wire> = T` — added to `src/shared/api/types.ts`
the first time it is needed.

## Gates

| Mistake | Caught by | Runs in | You see |
| --- | --- | --- | --- |
| Backend snapshot stale or hand-edited | `test_openapi_snapshot_is_current` | `just guards`, pre-commit, `backend.yml` | `the OpenAPI document changed; review the diff and run `just openapi-snapshot` if it is intended` |
| Vendored `openapi.json` stale or hand-edited | `contract-check` (a) | `just check`, pre-commit, `frontend.yml` | `contract-check: src/test/contract/openapi.json differs from backend/tests/guards/openapi.snapshot.json` + the first 40 diff lines |
| `schema.d.ts` stale or hand-edited | `contract-check` (b) | same | `✘ Generated types are not up-to-date!` |
| Wrong body, missing field, unknown path, missing path param | `tsc` through the path-typed client | `just typecheck`, pre-commit, `frontend.yml` | `Argument of type … is not assignable to parameter of type …` |
| `apiClient.get<MyType>(…)` | `tsc` | same | `Type 'MyType' does not satisfy the constraint 'BodylessPaths<"get">'` |
| Raw `axios` in a feature | ESLint `no-restricted-imports` | `just lint`, pre-commit, `frontend.yml` | `Only apiClient talks HTTP …` |
| Importing `generated/schema` or `openapi.json` outside the sanctioned files | same | same | `Import `Schema`, `ApiPath`, … from `@/shared/api/types` …` |
| `x as { … }` | ESLint `no-restricted-syntax` | same | `Don't cast to an inline object type …` |
| Request body or query the backend would 422 | runtime validator (`src/test/contract`, request kind) | `just test`, `frontend.yml` | `Contract violation(s) … Fix the service/component …` |
| Mock the backend cannot produce | runtime validator (response kind) | same | `… Fix the MSW handler/fixture …` |
| Type helpers drift from the generator's emission | `src/test/guards/api-types.guard.test.ts` | `just typecheck` | `expectTypeOf` errors |
| zod form bound drifts from its `*In` schema | `src/test/guards/form-schemas.guard.test.ts` | `just test` | `password.maxLength: wire 256, form undefined` |

A `contract-check` failure always ends with the remedy: `run `just contract-refresh` in frontend/
and commit the result`. The pre-commit hook `frontend-contract-check` fires on any commit that
touches either snapshot, the generated types, the scripts or `package(-lock).json` — including a
backend-only commit that ran `just openapi-snapshot`, which is the point.

## Never

- Hand-edit `openapi.snapshot.json`, `openapi.json` or `schema.d.ts`. Regenerate.
- Dump `app.openapi()` a second way. The backend snapshot is the one serialization.
- Call `allowContractViolations()` (it has zero uses; keep it that way).
- Cast to an inline object type, or import `axios` outside `api-client.ts` and the refresh call
  in `auth.service.ts`.
- `eslint-disable` one of these rules, or loosen a gate to make code pass. Fix the code.
- Bump `openapi-typescript` without regenerating in the same commit: it is exact-pinned because
  the check compares bytes.
- Branch-protect `main` without requiring "frontend / just ci" and "backend / just ci" — the
  workflows only bind when required.
