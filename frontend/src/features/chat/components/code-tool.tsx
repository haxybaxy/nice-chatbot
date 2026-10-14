import {
  CodeBlock,
  CodeBlockActions,
  CodeBlockCopyButton,
  CodeBlockHeader,
  CodeBlockTitle,
} from "@/shared/components/ai-elements/code-block";
import { Shimmer } from "@/shared/components/ai-elements/shimmer";
import { Terminal } from "@/shared/components/ai-elements/terminal";
import { ToolOutput } from "@/shared/components/ai-elements/tool";
import { Badge } from "@/shared/components/ui/badge";

import { ToolPartShell } from "./tool-part-shell";
import type { ChatToolPart, CodeOutput } from "../types";

type CodePart = Extract<ChatToolPart, { type: "tool-run_code" }>;

const ANSI_RED = "\u001b[31m";
const ANSI_RESET = "\u001b[0m";

/** stdout as written, stderr in red — what a terminal would have shown. */
function terminalText({ stdout, stderr }: CodeOutput): string {
  const err = stderr ? `${ANSI_RED}${stderr}${ANSI_RESET}` : "";
  return stdout && err ? `${stdout}${stdout.endsWith("\n") ? "" : "\n"}${err}` : stdout || err;
}

const TITLE: Record<CodePart["state"], (language: string) => string> = {
  "input-streaming": (language) => `Writing ${language}`,
  "input-available": (language) => `Running ${language}`,
  "approval-requested": (language) => `Running ${language}`,
  "approval-responded": (language) => `Running ${language}`,
  "output-available": (language) => `Ran ${language}`,
  "output-error": (language) => `Ran ${language}`,
  "output-denied": (language) => `Did not run ${language}`,
};

export function CodeTool({ part }: { part: CodePart }) {
  // While the model is still writing the call, `input` is a partial; the block waits for it.
  const input = part.state === "input-streaming" ? undefined : part.input;
  const language = input?.language ?? "code";

  return (
    <ToolPartShell part={part} title={TITLE[part.state](language)} open={input !== undefined}>
      {input && (
        <CodeBlock code={input.code} language={input.language}>
          <CodeBlockHeader>
            <CodeBlockTitle>{input.language}</CodeBlockTitle>
            <CodeBlockActions>
              <CodeBlockCopyButton aria-label="Copy code" />
            </CodeBlockActions>
          </CodeBlockHeader>
        </CodeBlock>
      )}
      {part.state === "input-streaming" && <Shimmer duration={1}>Writing code…</Shimmer>}
      {part.state === "input-available" && <Shimmer duration={1}>Running…</Shimmer>}
      {part.state === "output-error" && (
        <ToolOutput output={undefined} errorText={part.errorText} />
      )}
      {part.state === "output-available" && <CodeResult output={part.output} />}
    </ToolPartShell>
  );
}

function CodeResult({ output }: { output: CodeOutput }) {
  const failed = output.exitCode !== 0;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant={failed ? "destructive" : "secondary"}>exit {output.exitCode}</Badge>
        <Badge variant="outline">{output.durationMs} ms</Badge>
        {output.timedOut && <Badge variant="destructive">timed out</Badge>}
        {output.truncated && <Badge variant="secondary">output truncated</Badge>}
      </div>
      <Terminal output={terminalText(output)} autoScroll={false} data-testid="code-terminal" />
    </div>
  );
}
