/**
 * Chunk scripts for the run event stream — typed `UIMessageChunk[]`s a test hands to
 * `runEventsResponse` / `controllableRunEvents().push`. Shapes mirror what the backend's
 * tools and research graph write (`app/core/ui_stream.py`, `app/core/tools/schemas.py`): tool
 * inputs are the model's arguments as emitted (snake_case keys the UI does not read), tool
 * outputs are the `*Out` schemas dumped by alias (camelCase).
 */
import type { UIMessageChunk } from "ai";

export const ASSISTANT_MESSAGE_ID = "msg-a1";

export const SOURCE = {
  sourceId: "1",
  url: "https://docs.python.org/3.14/whatsnew/3.14.html",
  title: "What's New In Python 3.14",
} as const;

const start = (messageId: string): UIMessageChunk[] => [
  { type: "start", messageId },
  { type: "start-step" },
];
const finish: UIMessageChunk[] = [
  { type: "finish-step" },
  { type: "finish", finishReason: "stop" },
];
const text = (id: string, content: string): UIMessageChunk[] => [
  { type: "text-start", id },
  { type: "text-delta", id, delta: content },
  { type: "text-end", id },
];
/** A tool call that was emitted at once (no input deltas) and answered. */
const toolCall = (
  toolCallId: string,
  toolName: string,
  input: unknown,
  result: { output: unknown } | { errorText: string }
): UIMessageChunk[] => [
  { type: "tool-input-start", toolCallId, toolName },
  { type: "tool-input-available", toolCallId, toolName, input },
  "output" in result
    ? { type: "tool-output-available", toolCallId, output: result.output }
    : { type: "tool-output-error", toolCallId, errorText: result.errorText },
];

/** A plain answer. */
export function textRun({
  messageId = ASSISTANT_MESSAGE_ID,
  content = "Hello from the assistant.",
}: { messageId?: string; content?: string } = {}): UIMessageChunk[] {
  return [...start(messageId), ...text("t1", content), ...finish];
}

export const WEB_SEARCH_QUERY = "Python 3.14 changes";

/** A web search, a fetch of the top result, the numbered source, then an answer citing `[1]`. */
export function webSearchRun({ messageId = ASSISTANT_MESSAGE_ID } = {}): UIMessageChunk[] {
  return [
    ...start(messageId),
    ...toolCall(
      "call-search",
      "web_search",
      { query: WEB_SEARCH_QUERY, max_results: 5 },
      {
        output: {
          query: WEB_SEARCH_QUERY,
          results: [
            {
              sourceId: SOURCE.sourceId,
              title: SOURCE.title,
              url: SOURCE.url,
              snippet: "Template strings, deferred annotations and a new REPL.",
              publishedAt: "2026-10-07",
            },
          ],
        },
      }
    ),
    { type: "source-url", ...SOURCE },
    ...toolCall(
      "call-fetch",
      "web_fetch",
      { url: SOURCE.url },
      {
        output: {
          sourceId: SOURCE.sourceId,
          url: SOURCE.url,
          title: SOURCE.title,
          content: "Python 3.14 introduces template string literals (t-strings)…",
          chars: 64,
          truncated: false,
        },
      }
    ),
    { type: "finish-step" },
    { type: "start-step" },
    ...text("t1", "Python 3.14 adds template strings [1]."),
    ...finish,
  ];
}

export const CODE_SNIPPET = "print(17 * 23)";

/** The code tool: the program, then its terminal output with the given exit code. */
export function codeRun({
  messageId = ASSISTANT_MESSAGE_ID,
  exitCode = 0,
}: { messageId?: string; exitCode?: number } = {}): UIMessageChunk[] {
  return [
    ...start(messageId),
    ...toolCall(
      "call-code",
      "run_code",
      { language: "python", code: CODE_SNIPPET, timeout_s: 30 },
      {
        output: {
          stdout: exitCode === 0 ? "391\n" : "",
          stderr: exitCode === 0 ? "" : "Traceback: boom\n",
          exitCode,
          durationMs: 42,
          truncated: false,
          timedOut: false,
        },
      }
    ),
    { type: "finish-step" },
    { type: "start-step" },
    ...text("t1", exitCode === 0 ? "The answer is 391." : "The program failed."),
    ...finish,
  ];
}

/** The code tool failing before it could run (the sandbox is down). */
export function codeErrorRun({ messageId = ASSISTANT_MESSAGE_ID } = {}): UIMessageChunk[] {
  return [
    ...start(messageId),
    ...toolCall(
      "call-code",
      "run_code",
      { language: "bash", code: "echo hi" },
      { errorText: "Sandbox unavailable" }
    ),
    { type: "finish-step" },
    { type: "start-step" },
    ...text("t1", "I could not run the program."),
    ...finish,
  ];
}

export const RESEARCH_PLAN = {
  summary: "Compare the two approaches on cost and latency.",
  complexity: "medium",
  tasks: [
    {
      id: "t1",
      title: "Survey approach A",
      objective: "Find current benchmarks for A.",
      status: "pending",
    },
    {
      id: "t2",
      title: "Survey approach B",
      objective: "Find current benchmarks for B.",
      status: "pending",
    },
  ],
} as const;

/** A deep-research run: the plan, task t1 advancing in place, t2 done, the report, the citation check. */
export function researchRun({ messageId = ASSISTANT_MESSAGE_ID } = {}): UIMessageChunk[] {
  return [
    ...start(messageId),
    { type: "data-research-plan", id: "plan", data: RESEARCH_PLAN },
    {
      type: "data-research-task",
      id: "t1",
      data: {
        id: "t1",
        title: "Survey approach A",
        status: "running",
        toolCalls: 1,
        lastAction: "Searching benchmarks",
      },
    },
    {
      type: "data-research-task",
      id: "t1",
      data: {
        id: "t1",
        title: "Survey approach A",
        status: "done",
        toolCalls: 3,
        summary: "A is cheaper.",
      },
    },
    {
      type: "data-research-task",
      id: "t2",
      data: {
        id: "t2",
        title: "Survey approach B",
        status: "done",
        toolCalls: 2,
        summary: "B is faster.",
      },
    },
    { type: "source-url", ...SOURCE },
    ...text("t1", "## Findings\n\nA is cheaper while B is faster [1]."),
    {
      type: "data-research-citations",
      id: "citations",
      data: { unsupported: ["B is faster"], unknownNumbers: [7] },
    },
    ...finish,
  ];
}

/** The model declined. */
export function refusalRun({ messageId = ASSISTANT_MESSAGE_ID } = {}): UIMessageChunk[] {
  return [
    ...start(messageId),
    {
      type: "data-refusal",
      data: { category: "policy", explanation: "That request is out of scope." },
    },
    ...finish,
  ];
}

/** The transient title chunk the first run of a conversation emits. */
export function titleChunk(title: string): UIMessageChunk {
  return { type: "data-conversation-title", data: { title }, transient: true };
}
