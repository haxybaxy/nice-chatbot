import type { DynamicToolUIPart } from "ai";
import { useContext, useMemo } from "react";

import { MessageResponse } from "@/shared/components/ai-elements/message";
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/shared/components/ai-elements/reasoning";
import {
  Source,
  Sources,
  SourcesContent,
  SourcesTrigger,
} from "@/shared/components/ai-elements/sources";
import { ToolInput, ToolOutput } from "@/shared/components/ai-elements/tool";

import { CitationAnchor } from "./citation-anchor";
import { CodeTool } from "./code-tool";
import { DeepResearchPanel } from "./deep-research-panel";
import { RefusalNotice } from "./refusal-notice";
import { ToolPartShell } from "./tool-part-shell";
import { WebFetchTool } from "./web-fetch-tool";
import { WebSearchTool } from "./web-search-tool";
import type { ChatMessage, ChatToolPart } from "../types";
import { type AssistantBlock, toAssistantContent } from "../utils/assistant-blocks";
import { CitationSourcesContext } from "../utils/citation-sources";
import { hostnameOf, linkCitations } from "../utils/citations";
import { TOOL_PART_TYPES } from "../utils/wire-parts";

const markdownComponents = { a: CitationAnchor };

/**
 * An assistant message's parts, in order: merged reasoning, the sources it cited, text with
 * `[n]` citations linked, each tool call in its shell, the deep-research panel and refusals.
 */
export function AssistantMessage({
  message,
  isStreaming,
}: {
  message: ChatMessage;
  isStreaming: boolean;
}) {
  const { blocks, sources, research } = useMemo(
    () => toAssistantContent(message.parts),
    [message.parts]
  );

  return (
    <CitationSourcesContext.Provider value={sources}>
      {research && <DeepResearchPanel research={research} isStreaming={isStreaming} />}
      {sources.length > 0 && (
        <Sources>
          <SourcesTrigger count={sources.length} />
          <SourcesContent>
            {sources.map((source) => (
              <Source
                key={source.sourceId}
                href={source.url}
                title={`[${source.sourceId}] ${source.title ?? hostnameOf(source.url)}`}
              />
            ))}
          </SourcesContent>
        </Sources>
      )}
      {blocks.map((block) => (
        <AssistantBlockView key={block.key} block={block} isStreaming={isStreaming} />
      ))}
    </CitationSourcesContext.Provider>
  );
}

function AssistantBlockView({
  block,
  isStreaming,
}: {
  block: AssistantBlock;
  isStreaming: boolean;
}) {
  switch (block.kind) {
    case "reasoning":
      return (
        <Reasoning isStreaming={isStreaming && block.streaming} defaultOpen={false}>
          <ReasoningTrigger />
          <ReasoningContent>{block.text}</ReasoningContent>
        </Reasoning>
      );
    case "text":
      return <TextBlock text={block.text} isStreaming={isStreaming && block.streaming} />;
    case "tool":
      return <ToolView part={block.part} />;
    case "dynamic-tool":
      return <DynamicToolView part={block.part} />;
    case "refusal":
      return <RefusalNotice refusal={block.data} />;
  }
}

function TextBlock({ text, isStreaming }: { text: string; isStreaming: boolean }) {
  const sources = useContext(CitationSourcesContext);
  return (
    <MessageResponse components={markdownComponents} isAnimating={isStreaming}>
      {linkCitations(text, sources)}
    </MessageResponse>
  );
}

function ToolView({ part }: { part: ChatToolPart }) {
  switch (part.type) {
    case TOOL_PART_TYPES.webSearch:
      return <WebSearchTool part={part} />;
    case TOOL_PART_TYPES.webFetch:
      return <WebFetchTool part={part} />;
    case TOOL_PART_TYPES.code:
      return <CodeTool part={part} />;
  }
}

/** A tool this UI has no view for: parameters and result as JSON. */
function DynamicToolView({ part }: { part: DynamicToolUIPart }) {
  return (
    <ToolPartShell part={part} title={part.toolName}>
      {part.input !== undefined && <ToolInput input={part.input} />}
      <ToolOutput output={part.output} errorText={part.errorText} />
    </ToolPartShell>
  );
}
