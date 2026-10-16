# CLAUDE.md — frontend

Guidance for working in `frontend/`. `README.md` has the quick start; this file has the rules.

## Commands (run from `frontend/`)

```bash
npm ci                           # install (Node ≥ 22.22)
just dev                         # Vite on :3000 → backend on :8000
just check                       # fmt + lint + typecheck + deadcode + dup + cycles + fallow — run before every commit
just test                        # vitest run (MSW, no network); `just test -t "<name>"` or `just test src/features/auth`
just contract-refresh            # after any backend API change: backend snapshot → openapi.json → schema.d.ts; commit all three
just contract-check              # non-mutating drift check of that chain (in `just check`, pre-commit and CI)
just ui-add <component…>         # shadcn add + normalize (see Quality tooling notes)
just ai-add <component…>         # Vercel AI Elements add + normalize into shared/components/ai-elements/
```

React 19 · Vite 8 · TypeScript 5.9 (strict, `noUncheckedIndexedAccess`) · react-router 7 ·
TanStack Query 5 · axios · TanStack Form + zod 4 · Tailwind 4 · shadcn (Radix, `radix-nova`) ·
AI SDK 7 (`ai`, `@ai-sdk/react`) + AI Elements (Streamdown, shiki) · vitest 5 + MSW 2 + Testing
Library.

## Layout: package-by-feature

```
src/features/<name>/
├── index.ts           public API — the ONLY thing other code imports from the feature (knip entry)
├── components/        kebab-case.tsx
├── hooks/             use-<thing>.ts — TanStack Query hooks; every server read/write goes through one
├── pages/             PascalCasePage.tsx, default export (lazy-loaded from App.tsx)
├── schemas/           *.schemas.ts — zod, FORMS ONLY (never for parsing responses)
├── services/          <name>.service.ts — class + singleton; the only place that calls apiClient
├── types/index.ts     aliases of wire schemas: `export type UserProfile = Schema<"UserOut">`
├── utils/             (none today — token storage and auth-failure classification are shared)
└── __tests__/         <subject>.test.ts(x); multi-unit flows are *.integration.test.tsx
```

`src/shared/` holds what more than one feature needs: `api/` (typed access to the generated
schema; `request-options.ts` — the `path` / `query` option types both transports share),
`config/api-endpoints.ts` (every path), `constants/` (app name, routes, query keys, storage keys),
`services/` (api-client, sse-client, api-error, auth-bridge, token-storage, refresh-error,
local-storage), `utils/` (`cn`), `hooks/` (`use-mobile`, written by shadcn), `components/` (shadcn
`ui/`, AI Elements `ai-elements/`, `form/` — the TanStack Form kit —, `feedback/`, `error-boundary/`). `src/providers/` composes
Query → Auth → Theme (+ `toaster.tsx`); each provider `.tsx` has a sibling `use-*.ts` with the
context + hook so react-refresh stays clean. `src/layouts/` are the route shells (`AuthLayout`,
`ProtectedLayout`, `ChatLayout` — see Routing). `src/App.tsx`
and `src/main.tsx` are composition roots. Import direction between these directories is
enforced by fallow boundaries (see Quality tooling notes).

## Conventions

- **Server state is TanStack Query, always.** Hooks live in `features/*/hooks`, keys in
  `shared/constants/query-keys.ts` (hierarchical; `QUERY_KEYS.<feature>.all` is the invalidation
  prefix). Mutations invalidate what still exists and `removeQueries` what a delete made 404.
  Multi-argument mutations take one object so `onSuccess(_, vars)` can destructure.
  **The one exception is the live chat thread**: `useChat` (`@ai-sdk/react`) owns a
  conversation's messages while a response streams. `features/chat/hooks/use-conversation-chat.ts`
  is the only place it is called and keeps the query side honest around it — the thread mounts
  from the persisted `ConversationDetailOut` (`toChatMessage`, frozen at mount: `useChat` keys
  its instance by `id`, so a later refetch neither resets the messages nor flips `resume`),
  resumes when the row had an `activeRun`, patches the streamed `data-conversation-title` into
  the list/detail caches in `onData`, invalidates both in `onFinish`, and refetches the
  persisted thread into `setMessages` when a resume finds no run (it finished while we were
  away). Nothing else reads or writes `useChat` state; the sidebar, the header and the next
  mount all read the query caches. **Attachments** are uploaded by the composer before the
  message (`useUploadAttachments`, one `AttachmentOut` per file; a refused file keeps the
  composer as it was) and enter the thread as SDK `FileUIPart`s built from those rows
  (`toFileUIPart`: `mediaType`, `filename`, `url`), so the optimistic user message and the
  persisted one render through the same `FilePart`. The transport maps them back with the pure
  `utils/message-parts.ts` (`toMessagePartsIn`: text → `TextPartIn`, file → `FilePartIn{type,
attachmentId}` with the id read from `/api/attachments/{id}/content`; the request schema is
  `extra="forbid"`, so nothing else goes); the new-conversation screen uses the same helper. The
  composer owns its pending files (`useComposerAttachments`: picker, drop, paste, limits) because
  the vendored `PromptInput` hands `onSubmit` data/blob URLs, not the `File`s a multipart body
  needs.
- **Only `apiClient` talks HTTP** — never raw `fetch`/`axios` in a feature (enforced: ESLint bans
  `axios` outside `api-client.ts` and the refresh call in `auth.service.ts`, which must bypass the
  interceptor). The client is **path-typed**: `apiClient.get(API_ENDPOINTS.USERS.ME)`,
  `apiClient.post(API_ENDPOINTS.AUTH.SIGNIN, body, { skipAuth: true })` — the path + verb pick the
  body, the `path`/`query` options and the result from the spec; there is no `<T>`. A bodyless
  verb is `post(path)`; with options, `post(path, undefined, { skipAuth: true })`. Paths come from
  `API_ENDPOINTS` (each group `satisfies Record<string, ApiPath>`, so a typo is a compile error).
  Errors arrive as `ApiError` (`status`, `code` = the generated `ErrorCode`, `correlationId`,
  `detail` = the backend's `error` message; defined in `shared/services/api-error.ts`, re-exported
  by `api-client.ts`).
  Two more shapes ride the same client: `apiClient.upload(path, formData, options)` for the
  operations the spec declares as `multipart/form-data` (`FormPaths<"post">`; the field names are
  `FormBody<P, "post">`, and the JSON verbs refuse those paths — today only the attachment upload)
  and `apiClient.blob(path, options)` → `Blob` for the binary routes (`responseType: "blob"`).
  **A bearer-protected binary is never a `src`/`href`**: fetch it through `blob`, show it through
  `URL.createObjectURL`, and tie the URL's life to the query that holds it — see
  `features/chat/hooks/use-attachments.ts` (`useAttachmentObjectUrl`: created in the `queryFn`,
  `staleTime: Infinity`, revoked by one cache subscription per QueryClient when the query is
  garbage-collected or removed).
  **The one exception is `text/event-stream`**: `shared/services/sse-client.ts` exports
  `openEventStream(path, { path, query, signal })` — path-typed like `apiClient.get`, same bearer
  header, pre-emptive refresh when the access token is expired, one refresh + retry on 401 and
  the same `ApiError` — and resolves with the raw `ReadableStream`, which the chat transport
  parses with the AI SDK (`parseJsonEventStream` + `uiMessageChunkSchema`; stream payloads are
  typed by `UIMessageChunk` and sit outside the JSON contract validator). ESLint
  `no-restricted-globals` bans `fetch`, `EventSource`, `XMLHttpRequest` and `WebSocket` everywhere
  but that file.
- **Generated API types** — the whole chain and its gates are in `docs/api-contract.md`.
  `schema.d.ts` is generated by openapi-typescript from `src/test/contract/openapi.json`, a byte
  copy of the backend's guarded snapshot; `just contract-refresh` walks the chain and
  `just contract-check` fails when a link is stale. `src/shared/api/types.ts` is the only reader
  of the generated module (ESLint): it exports `Schema<"X">` for aliases and `ApiPath` /
  `PathsWith` / `RequestBody` / `PathParams` / `QueryParams` / `SuccessBody` for the client and
  `mockApi`. Never hand-declare a shape that exists in the spec; alias it
  (`export type UserProfile = Schema<"UserOut">`). If two endpoints return different schemas, keep
  two aliases (`AuthUser` vs `UserProfile` — the session cache type `SessionUser` is the documented
  union). Never narrow a response type by hand. Inline `as { … }` casts are banned (ESLint); the
  two allowed hand-written kinds are client-only shapes (`SessionUser`, a cache state) and named
  structural probes on error objects (`shared/services/refresh-error.ts`), each commented as such.
- **Forms are TanStack Form through one kit** (`shared/components/form/`): `useAppForm({
defaultValues, validationLogic: revalidateLogic(), validators: { onDynamic: <zod schema> },
onSubmit: submitMutation((value) => mutation.mutateAsync(value)) })` — validate on submit,
  re-validate on change from then on, and the awaited mutation drives `isSubmitting`. The body is
  `<form.AppForm><form.Root>…</form.Root></form.AppForm>` (`Root` is the `<form>` element wired
  to `handleSubmit`); fields are `<form.AppField name="…">{(field) => <field.TextField
label="…" />}</form.AppField>` (the bound `TextField` reads its value, errors and disabled
  state from the field context); the button is `<form.SubmitButton pendingLabel="…">…</form.SubmitButton>`;
  the server's rejection is `<FormAlert error={mutation.error} />` (`form/form-alert.tsx`).
  Schemas stay zod, FORMS ONLY, and guarded (`form-schemas.guard.test.ts`).
- **Requests are `extra="forbid"` on the backend.** Send exactly the wire fields (map form data
  explicitly, as `sign-up-form.tsx` does with `confirmPassword`).
- **Auth**: access token in memory, refresh token in localStorage (`tokenStorage`, in
  `shared/services/token-storage.ts` because `api-client` reads it on every request); session
  restore and 401 refresh are in `auth.service.ts` / `api-client.ts`. Guards: `ProtectedRoute`,
  `GuestRoute` — both wait for `isLoading` before deciding. `useSignOut` must remove every
  feature cache (add to its `removeQueries` predicate as features arrive).
- **Routing**: paths in `ROUTES`; pages lazy. `layouts/ProtectedLayout.tsx` is a bare shell —
  the `ProtectedRoute` gate and a route-keyed error boundary, no chrome (cross-route hooks go
  there, not in pages). `/app` renders `AppIndexRedirect` (`features/teams`): the team in
  `STORAGE_KEYS.LAST_TEAM_ID` when it is still one of the caller's, else the first. Everything
  team-scoped lives under `/app/teams/:teamId` in `layouts/ChatLayout.tsx`, which calls
  `useCurrentTeam()` (validates the id against `GET /api/teams`, remembers it, redirects an
  unknown one) and owns the shadcn `SidebarProvider` + `ChatSidebar` (team switcher, "New
  chat" — also `⌘⇧O` —, the conversation list by day, the account menu with the theme and sign
  out) + a `h-svh` `SidebarInset` for the thread; `chat` and `chat/:conversationId` both render
  `ChatPage`. The page owns the composer's choices (`useComposerSettings`) because the model
  picker sits in `ChatHeader` next to the sidebar toggle while the thread sends with them; the
  conversation title is the browser tab's title and an sr-only heading, not visible chrome.
  There is no `home` feature any more: a signed-in user always lands in a chat.
- **Styling**: Tailwind utilities + shadcn tokens from `globals.css` (`bg-background`,
  `text-muted-foreground`, …). Dark mode is the `.dark` class set by `ThemeProvider`. `cn()` from
  `@/shared/utils` for class merging.
- **Typing**: `strict` + `noUncheckedIndexedAccess` + `noPropertyAccessFromIndexSignature`; a
  written `any` fails lint. Every `eslint-disable` must name its rule and be needed
  (`reportUnusedDisableDirectives: "error"`).
- **Imports**: `@/…` for cross-directory, relative inside a feature; `import-x/order` is
  auto-fixed by `just lint`.

## Testing (`src/test/`)

- Vitest + jsdom + Testing Library. `renderWithProviders(ui, { authenticated, route })` mounts the
  real Query/Auth/Theme tree in a `MemoryRouter`; `authenticated: true` (default) seeds a JWT-shaped
  access token + refresh token so `/users/me` resolves.
- **MSW with `onUnhandledRequest: "error"`**: every endpoint a test hits needs a handler in
  `src/test/msw/handlers/` (registered in `handlers/index.ts`), built from the typed `make*()`
  fixtures in `msw/fixtures/` (`run-chunks.ts` holds the typed `UIMessageChunk[]` scripts —
  `textRun`, `webSearchRun`, `codeRun`, `researchRun`, `refusalRun` — the stream mocks replay). Handlers register through `mockApi.<verb>(API_ENDPOINTS…, resolver)`
  (`msw/typed-http.ts`): `request.json()` is the operation's `*In` schema and the response must be
  its `*Out` schema or `errorResponse(status, code)` (`msw/fixtures/error.ts`) — no casts. Override
  per test with `server.use(...)`. Prefer MSW over `vi.mock` for anything HTTP.
- **Event streams** are mocked with `src/test/msw/sse.ts`: `sseBody(chunks, { firstSeq })` frames
  typed `UIMessageChunk`s the way the backend replays a run (`id: <seq>` + `data:`, closed by
  `data: [DONE]`), `runEventsResponse(chunks)` wraps that with `UI_MESSAGE_STREAM_HEADERS`,
  `controllableRunEvents()` returns `{ response, push, end, aborted }` for in-progress / aborted
  streams, and `mockRunEvents(path, resolver)` registers through a raw `http.get(url(path))`
  because `mockApi` types a response as the operation's JSON `*Out` schema (the contract
  validator skips `text/event-stream` for the same reason). The attachment content route is
  binary and registers the same way (`mockAttachmentContent` + `attachmentContentResponse` in
  `handlers/attachments.ts`); the upload handler is a plain `mockApi.post` reading
  `request.formData()`. `setup.ts` stubs `ResizeObserver`,
  `IntersectionObserver` and `Element.prototype.scrollTo` for the AI Elements, replaces
  `URL.createObjectURL` / `revokeObjectURL` with deterministic `vi.fn`s (`blob:mock/<n>`; assert
  on them with `vi.mocked`), and holds the
  only `vi.mock` in the suite — `shiki`, which is not HTTP (a no-highlight stub so code blocks
  render synchronously and offline). Everything HTTP stays MSW.
- **Both directions of the contract are enforced** by `src/test/contract/` in `afterEach`:
  request bodies + query params against the spec's `*In` schemas (unknown field → fail), and
  mocked 2xx JSON responses against the `*Out` schemas (missing required field / wrong type →
  fail). A request violation means the service/component is wrong; a response violation means
  the mock is wrong. Never edit `openapi.json` to silence either — regenerate it
  (`just contract-check`, in `just check`, pre-commit and `frontend.yml`, fails on a stale copy).
  `allowContractViolations()` exists as an escape hatch; there are zero uses — keep it that way.
- **Guards** (`src/test/guards/*.guard.test.ts`, the analogue of the backend's `tests/guards/`):
  `api-types` pins the type helpers to the generator's emission (`expectTypeOf`, checked by
  `tsc`); `form-schemas` fails when a zod form bound drifts from the `*In` schema it submits to.
- Tests live in `__tests__/` beside the subject and are named after it; user-visible flows are
  `*.integration.test.tsx` and render `<App />` at a route.
- Coverage (`just cov`) is reporting only; quality is enforced structurally (contract validator,
  knip, jscpd, unhandled-request errors), not by a percentage.

## Quality tooling notes

- **knip** entries are `index.html`, `src/features/*/index.ts` and the vendored registry files
  (next bullet) — a feature without a barrel reports every file in it as unused. Unused exports
  are warnings: trim them in our own code.
  Packages only CSS imports (`tailwindcss`, `shadcn`, `tw-animate-css`) are in
  `ignoreDependencies` because knip doesn't follow `@import`.
- **Vendored registry code** — shadcn `shared/components/ui/**`, Vercel AI Elements
  `shared/components/ai-elements/**` and `shared/hooks/use-mobile.ts` — is kept as shipped so a
  re-add diffs cleanly against upstream. It is exempt from the size / complexity gates: ESLint
  turns off `max-lines`, `max-lines-per-function`, `complexity`,
  `react-refresh/only-export-components` and the three React Compiler diagnostics
  (`react-hooks/refs`, `set-state-in-effect`, `static-components`) there (`VENDORED_FILES` in
  `eslint.config.mjs`); fallow `health.ignore` + `duplicates.ignore`, `.jscpd.json` and the
  coverage `exclude` list the same paths; knip and fallow treat the files as entries, so a
  sub-component nothing imports yet is not dead code and their unused exports are not reported.
  What stays on: the import bans, the HTTP-globals ban and `no-explicit-any` — fix those by hand
  (the blob-URL `fetch` in `prompt-input.tsx` carries the one named disable). Don't trim
  `prompt-input.tsx` / `sidebar.tsx` piecemeal; delete a whole file the app will never use.
- **shadcn 4** writes `import { cn } from "cn"` (its own `cn` package) and pulls `next-themes`
  for the toaster. `just ui-add` rewrites the import to `@/shared/utils` and removes both
  packages so there is one `cn` in the codebase; `sonner.tsx` takes `theme` as a prop and
  `providers/toaster.tsx` feeds it from our `ThemeProvider` — don't `--overwrite` it. Both
  recipes answer shadcn's "file exists, overwrite?" prompts with no (`--yes` doesn't), so an
  already-vendored dependency such as `button.tsx` is kept. `just ai-add <name…>` does the same
  for AI Elements (`https://elements.ai-sdk.dev/api/registry/<name>.json`; the registry targets
  `src/components/` literally, the recipe moves the files under `src/shared/`). `message.tsx` and
  `reasoning.tsx` keep only the `@streamdown/code` Streamdown plugin (mermaid / math / cjk are
  uninstalled — they pull bundles the app never renders), and `globals.css` carries the
  `@source` lines Streamdown's classes need. The vendored `entry` globs stay in `knip.json` and
  `.fallowrc.json` even though the chat feature imports most of the files: sub-components nothing
  imports yet (`task.tsx`'s file badges, the prompt-input tabs/commands, message branches) are
  the library's surface, not dead code.
- **jscpd** fails above 2 % duplication (tests excluded) — extract a component (see
  `shared/components/form/text-field.tsx`, `features/auth/components/auth-card.tsx`) instead of
  raising the threshold. Its `format` list must say `typescript`,
  not `ts` (jscpd 5 silently scans nothing for an unknown format name). **madge** fails on any
  import cycle; `auth-bridge.ts` exists precisely to keep `api-client` ↔ `auth.service` acyclic.
- **fallow** (`.fallowrc.json`, `just fallow`) runs dead code, duplication, complexity and
  architecture boundaries in one sub-second pass, on top of knip/jscpd/madge (it overlaps them;
  the boundaries and per-function complexity ceilings are what only it provides). Policy:
  unused exports/types are warnings like knip; unused files, unlisted/unused/unresolved
  dependencies, cycles and boundary violations are errors; functions above cyclomatic 20 /
  cognitive 15 fail — split them (`buildRoutes` and `findDrift` were) rather than adding a
  `health.thresholdOverrides` entry. The CRAP gate is off (`maxCrap: 10000`) because it needs
  coverage data and coverage is reporting-only here. Fallow's `*` crosses `/`, so the feature
  barrels are listed explicitly in `entry` and in the `feature-api` zone. Zones (first match
  wins): `test` (`src/test/`, `__tests__/` — unrestricted), `feature-api` (barrels),
  `feature-pages`, one `features/<name>` zone per feature (auto-discovered, so sibling internals
  are isolated), `providers`, `app` (`App.tsx`, `main.tsx`, `layouts/`), `shared`. Rules: `app` →
  barrels, pages, providers, shared; `providers` → barrels, shared (+ type-only feature
  internals, for `SessionUser`); `feature-pages` → own internals, barrels, providers, shared;
  `features/<x>` → shared, providers, other barrels; `shared` imports nothing above it. Fix a
  violation by moving code down (`token-storage`, `refresh-error` moved to `shared/services`)
  or passing data in (`sonner.tsx` takes `theme`), never with `// fallow-ignore-next-line`.
  A `WARN … matched 0 reachable files` line for the `features` zone is expected (every file
  under `src/features/` is claimed by a more specific zone first). `.fallow/` is its cache
  (gitignored).
- **TypeScript is pinned to 5.x**: typescript-eslint and madge don't support TS 7 yet.
  **`eslint-plugin-import-x`** (not `eslint-plugin-import`) because ESLint 10.
- Generated files (`src/shared/api/generated/`, `src/test/contract/openapi.json`) are excluded
  from prettier (`.prettierignore`), eslint (`globalIgnores`), jscpd (`.jscpd.json`), coverage and
  the root pre-commit fixers on purpose; knip needs no entry (it reports nothing on the
  declaration file and flags an `ignoreFiles` entry as unnecessary). Regenerate, never edit.
- **Gates**: pre-commit (repo root) runs prettier, eslint, tsc, fallow and the contract check on
  every commit; `.github/workflows/frontend.yml` runs `just ci` for `frontend/**` and for the
  backend OpenAPI snapshot, so a backend change that skipped `just contract-refresh` fails there.

## Adding a feature

1. `src/features/<name>/` with `index.ts`, `types/index.ts` (aliases), `services/<name>.service.ts`,
   `hooks/use-<name>.ts` (keys added to `QUERY_KEYS`), `components/`, `pages/`. Add
   `src/features/<name>/index.ts` to `.fallowrc.json` twice: `entry` and the `feature-api` zone
   (forgetting it fails `just fallow` with `app → features/<name>` as soon as `App.tsx` imports
   the barrel).
2. Paths in `API_ENDPOINTS` (spec paths only); routes in `ROUTES` + `App.tsx`; caches in
   `useSignOut`'s cleanup. Types are `Schema<"…">` aliases and the client's inferred results —
   nothing hand-written. A payload the spec types as `unknown` (a tool's output, a `data-*`
   part) gets a hand-written type anchored with `Narrows<Wire, T>` (`shared/api/types.ts`) and
   a runtime guard at the one place it is narrowed (`features/chat/utils/payload-guards.ts`),
   never a cast.
3. Handlers (`mockApi`) + fixtures in `src/test/msw/`; at least one `*.integration.test.tsx` per
   user flow.
4. `just check && just test`.
