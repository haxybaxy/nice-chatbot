"""TEMPORARY vulture whitelist — seams whose consumers land with the chat feature (plan Phases 1–2).

Each name below is defined now (settings, session scope, UI stream, model catalog) and read by a
module that is still being written. Remove a name when its consumer exists; delete this file and
its `paths` entry in pyproject.toml before the feature is called done.
"""


class _Pending:
    pass


_ = _Pending()

# app/core/config.py
_.agent_settings
_.search_settings
_.sandbox_settings
_.research_settings
_.langfuse_settings
_.configured
_.langfuse_base_url
_.research_max_subagents
_.research_max_parallel
_.research_max_tool_calls_per_subagent
_.research_max_output_tokens_per_subagent
_.research_total_token_budget
_.research_wall_clock_s
_.research_citation_check

# app/core/ui_stream.py / ui_fold.py
_.EventSink
_.CancelToken
_.requested
_.request
_.wait
_.BufferedEventSink
_.data_chunk
_.source_url_chunk

# app/core/llm/catalog.py
_.is_available
_.title_model
_.cheaper
_.input_usd_per_mtok
_.output_usd_per_mtok
_.cache_read_multiplier

# settings fields read by the worker, the model builder, the tools and the sandbox
_.agent_checkpoint_schema
agent_checkpointer
agent_max_model_calls
agent_max_tool_calls
agent_max_tool_calls_per_step
anthropic_base_url
chat_history_max_messages
chat_run_timeout_s
chat_title_timeout_s
llm_max_retries
llm_max_tokens
llm_openai_max_tokens_param
llm_openai_parallel_tool_calls
llm_request_timeout_s
openai_api_key
sandbox_backend
sandbox_cpus
sandbox_image
sandbox_max_output_bytes
sandbox_max_timeout_s
sandbox_memory
sandbox_pids_limit
sandbox_timeout_s
search_max_concurrency
search_timeout_s
worker_concurrency
worker_event_flush_ms
worker_heartbeat_interval_s
worker_poll_interval_s
worker_reaper_interval_s
worker_shutdown_grace_s

# ── Consumed only by app/worker.py (Phase 1.4 / 2), which lands after the chat domain ──────────
# app/chat/use_cases: the worker-side queue operations
_.ClaimRun
_.TouchRun
_.RecordRunEvents
_.SaveAssistantMessage
_.FinishRun
_.ReapStaleRuns
_.owned
_.cancel_requested
# app/db/listen.py: the worker's startup log (PgListener.wait shares its name with CancelToken.wait above)
_.listening
