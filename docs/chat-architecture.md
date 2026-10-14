# Chat architecture

How a message becomes a streamed, persisted, traced answer. Decisions behind this are in
`docs/adr/0001-langgraph-worker-and-event-log.md`.

```
SPA (useChat + ConversationRunTransport)
  │ POST /api/conversations/{id}/messages  ──►  API: user message + run(queued) + NOTIFY run_queue
  │ GET  /api/conversations/{id}/runs/{run}/events  (SSE, AI SDK UI Message Stream)
  ▼                                                   ▲ replay run_event rows, then LISTEN run_events
Worker (python -m app.worker)
  claim run (FOR UPDATE SKIP LOCKED) → heartbeat → LangGraph graph (chat or deep research)
  → chunks → BufferedEventSink → run_event rows + NOTIFY → per-step message.parts upsert
  → finish | abort | error → run terminal, checkpoint thread deleted, Langfuse flushed
```

## Data

| Table | Role |
|---|---|
| `conversation` | belongs to a `team`; `visibility` `team` (default) or `private` (creator only); `last_message_at` orders the list |
| `message` | `role`, `position`, `parts` (the UI message parts), `provider_messages` (the turn's LangChain messages, serialized, for verbatim same-provider replay), usage |
| `run` | the queue item and the state machine: `queued → running → succeeded | failed | cancelled`; `attempt`, `heartbeat_at`, `cancel_requested_at`, `last_seq`, `trace_id`; at most one active run per conversation (partial unique index) |
| `run_event` | `(run_id, seq)` → one UI chunk (JSON) — the replay log for SSE |
| `langgraph.*` | LangGraph's checkpointer tables, in their own schema (created by the worker, invisible to Alembic) |

## Request flow

1. `POST …/messages` validates the model against the catalog, inserts the user message and a
   `queued` run in one transaction, and `pg_notify('run_queue')`s on commit. A second message
   while a run is active is a 409.
2. The SPA opens the run's `/events` stream. The API replays persisted chunks (`id:` = sequence,
   `data:` = chunk JSON) and tails new ones through `LISTEN run_events`, pinging every 15 s. It
   closes after a terminal chunk (`finish`, `error`, `abort`) with `data: [DONE]`.
3. A worker claims the run, opens a Langfuse root span (session = conversation, user, team/mode/
   model tags), builds the LangChain history (same provider → verbatim replay incl. thinking
   blocks; other provider → text + tool calls rebuilt from parts), and runs the graph with
   `thread_id = run id`. Chunks are coalesced (~75 ms) and written as `run_event` rows; after each
   step the assistant message's `parts` and `provider_messages` are upserted (append-only).
4. Cancel: `POST …/runs/{run}/cancel` flips `cancel_requested_at` and notifies `run_control`;
   the worker stops between chunks and emits `abort`.
5. Loss: a running run whose heartbeat is older than `WORKER_STALE_AFTER_S` is re-queued once
   (`attempt = 2`); the next worker resumes the LangGraph thread from its checkpoint (or restarts
   the turn when no checkpoint exists), emitting `reset-step` first only when the prior log ended
   inside an open step so the client drops exactly the partial step. `message.parts` is always the
   fold of the whole event log. A second loss fails the run with the partial message kept.

## Resume protocol (client)

`useChat` cannot continue a text part it never saw, so the client never asks for `?after=`.
`GET /api/conversations/{id}` omits the assistant message of an active run; on mount with an
active run the transport replays the stream from sequence 0 and the `start{messageId}` chunk
makes the rebuilt message replace the persisted one by id. `?after=` / `Last-Event-ID` remain for
raw consumers and tests.

## Tools and citations

`web_search` / `web_fetch` (Tavily behind `SearchClient`) and `run_code` (a throwaway Docker
container behind `SandboxClient`) are LangChain tools built per run with the run's context
(cancel token, source registry, budgets, tracer). Every source gets a run-wide number; tool
results label them `[n]`, the system prompt mandates `[n]` citations, and each new source is
streamed once as a `source-url` part. Deep research is a mode: a planner, parallel subagents on
the cheaper sibling model, a synthesized report with `[n]` and a confidence & gaps section, and
a citation check, all reported through `data-research-*` parts.

## Observability

Langfuse's LangChain callback handler runs under the per-run root span; tools open nested spans
for Tavily and sandbox calls; `run.trace_id` is deterministic from the run id. Without
`LANGFUSE_*` keys the tracer is a no-op. Structlog correlation ids cover the API side.
