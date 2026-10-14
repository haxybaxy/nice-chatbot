"""TEMPORARY vulture whitelist — seams whose consumers land with the chat worker (plan Phase 1.4).

Every name below is defined (settings, queue use cases, the agent core's worker-facing API) and
read by `app/worker.py` / `RunAssistantTurn`, which are written last. Delete this file and its
`paths` entry in pyproject.toml when the worker lands.
"""


class _Pending:
    pass


_ = _Pending()

_.BufferedEventSink
build
build_research_graph
cancel_requested
chat_history_max_messages
chat_run_timeout_s
chat_system_message
chat_title_timeout_s
cheaper
CheckpointerDep
CITATION_SCHEMA
citations
ClaimRun
close_search_client
delete_thread
dump_turn
EventSink
final_answer_only
FinishRun
input_usd_per_mtok
is_available
listening
LlmDep
max_output_tokens_per_subagent
model_calls
model_kwargs
output_usd_per_mtok
owned
PLAN_SCHEMA
ReapStaleRuns
RecordRunEvents
research_input
RESEARCH_STREAMED_NODES
run_context
sandbox_timeout_s
SandboxDep
SaveAssistantMessage
SearchDep
seed
stream_research
title_messages
title_model
TITLE_SCHEMA
to_langchain
tool_calls_made
ToolsDep
TouchRun
TracerDep
wall_clock_s
worker_concurrency
worker_event_flush_ms
worker_heartbeat_interval_s
worker_poll_interval_s
worker_reaper_interval_s
worker_shutdown_grace_s
