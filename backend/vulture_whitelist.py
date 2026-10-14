"""TEMPORARY vulture whitelist — seams whose consumers land with the chat feature (plan Phases 1–2).

Each name below is defined now and read by a module that is still being written (the chat
domain, ``app/worker.py``, the API lifespan). Remove a name when its consumer exists; delete this
file and its `paths` entry in pyproject.toml before the feature is called done.
"""


class _Pending:
    pass


_ = _Pending()

# app/db/session.py
_.session_scope
_.get_session_scope
_.SessionScopeDep

# app/core/config.py — read by the chat domain / the worker loop
_.chat_settings
_.worker_settings
chat_history_max_messages
chat_run_timeout_s
chat_sse_ping_interval_s
chat_title_timeout_s
llm_default_effort
worker_concurrency
worker_event_flush_ms
worker_heartbeat_interval_s
worker_poll_interval_s
worker_reaper_interval_s
worker_shutdown_grace_s
worker_stale_after_s

# app/core/ui_stream.py — the worker's sink and the SSE reader
_.EventSink
_.BufferedEventSink

# app/core/llm/catalog.py — the chat API (ListModels / ModelOut) and the worker
_.available
_.is_available
_.default
_.title_model
_.cheaper
_.is_default
_.display_name
_.tier
_.input_usd_per_mtok
_.output_usd_per_mtok
_.cache_read_multiplier

# ── Agent core (Phase 2): public API consumed only by app/worker.py / RunAssistantTurn ─────────
# ChatModelFactory.build is what the worker calls; `model_kwargs` is read by langchain-anthropic.
_.build
_.model_kwargs
# Default per-execution timeout advertised to the chat API's run options.
sandbox_timeout_s
# FastAPI dependency aliases, wired when the chat domain's dependencies land.
_.LlmDep
_.ToolsDep
_.TracerDep
_.CheckpointerDep
_.SearchDep
_.SandboxDep
# Tracer: the per-run root span and the shutdown hook.
_.run_context
_.shutdown
# Checkpointer lifecycle and per-run cleanup.
_.delete_thread
# History: persisted rows → model input, and the turn dump stored on the assistant message.
_.to_langchain
_.dump_turn
# Prompts: the chat system message and the title prompt.
_.chat_system_message
_.title_messages
_.TITLE_SCHEMA
# Stream mapper and the research entry points.
_.map_graph_stream
_.build_research_graph
_.research_input
_.stream_research
_.RESEARCH_STREAMED_NODES
_.PLAN_SCHEMA
_.CITATION_SCHEMA
_.from_settings
_.max_output_tokens_per_subagent
_.wall_clock_s
# Resume: the worker seeds the source numbering from persisted source-url parts.
_.seed
# Search client pool, closed from the lifespan / worker shutdown.
_.close_search_client
# LangGraph state keys, read by string inside the graphs.
_.model_calls
_.tool_calls_made
_.final_answer_only
_.citations
