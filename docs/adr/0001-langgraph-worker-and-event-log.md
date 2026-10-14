# ADR 0001 — Chat runs: LangGraph in a worker, a Postgres event log, the AI SDK stream protocol

Status: accepted · Date: 2026-10-14

## Context

The template needs team-scoped chat with web search, deep research and code execution, durable
enough that a reload or an API restart does not lose an answer in progress, observable enough to
debug and cost, and portable across model providers (Claude and OpenAI-compatible local servers).
The boilerplate it extends has a strict FastAPI backend (guards for layering, commits, schemas),
Postgres only (no Redis, no queue), and a React SPA whose wire types are generated from the
backend's OpenAPI snapshot.

## Decisions

1. **Provider-agnostic models through LangChain integrations.** Claude via `langchain-anthropic`
   (`ChatAnthropic`, default `claude-opus-5-5`, adaptive thinking, `effort`), OpenAI-compatible
   servers via `langchain-openai` (`ChatOpenAI(base_url=…)`). Claude never goes through the
   OpenAI shim (a settings validator rejects `openai:claude-*`). A settings-driven allowlist is
   the model picker.
2. **LangGraph runs the agent loop.** An explicit `StateGraph` (model node → `ToolNode` → loop,
   with step and tool budgets) for chat and a separate graph (plan → `Send` fan-out → synthesize
   → citation check) for deep research. Graph state is checkpointed per run with LangGraph's
   Postgres saver in a dedicated `langgraph` schema so Alembic never sees its tables; a lost
   worker re-queues the run once and the next worker resumes the same thread.
3. **Durable runs on Postgres alone.** A `run` row is the queue item (claimed with
   `FOR UPDATE SKIP LOCKED`, heartbeated, reaped), `run_event` is an ordered log of the chunks a
   run produced, and `LISTEN/NOTIFY` wakes workers and SSE readers. No Redis and no queue
   library: one schema, one state machine, migrations owned by Alembic.
4. **The AI SDK UI Message Stream is the wire format.** The worker writes chunks in that
   vocabulary, the API replays them over SSE (`id:` = sequence), and the SPA consumes them with
   `@ai-sdk/react`'s `useChat` through a custom transport plus AI Elements components. Persisted
   `message.parts` mirror the UI message shape, so REST and replay produce identical messages.
   Resume is a full replay from sequence 0 into a client that dropped its partial message.
5. **Provider-neutral tools behind Protocols.** `web_search`/`web_fetch` over a `SearchClient`
   (Tavily), `run_code` over a `SandboxClient` (a throwaway Docker container per execution in
   development; a hosted sandbox adapter in production). Sources are numbered per run and cited
   as `[n]`.
6. **Langfuse captures every run.** Its LangChain callback handler runs inside a per-run root
   span (`session_id` = conversation, `user_id`, team/mode/model tags); tools open nested spans;
   the trace id is stored on the run. A `Tracer` Protocol with a no-op keeps tests and keyless
   development offline.

## Consequences

- Two processes (API + worker) and a Docker socket for the sandbox in development; the compose
  `app` profile and `just dev` run both.
- Anthropic-only conveniences (server-side web search, refusal fallbacks) are deliberately not
  used in v1 so the UI and the citation convention stay provider-neutral; they are opt-in
  extensions.
- The frontend has exactly one raw `fetch` site (the SSE client) and one state exception (a
  mounted thread's messages are owned by `useChat`), both enforced by lint and documented.
