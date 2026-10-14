import type { ChatStatus } from "ai";
import { CodeIcon, GlobeIcon, MessageSquareIcon, TelescopeIcon } from "lucide-react";
import { useState } from "react";

import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from "@/shared/components/ai-elements/prompt-input";

import { ModelSelect } from "./model-select";
import { type ComposerSettings, resolveModelId } from "../hooks/use-composer-settings";
import type { ChatModel, RunMode } from "../types";

interface ChatComposerProps {
  status: ChatStatus;
  onSubmit: (text: string) => void | Promise<void>;
  onStop: () => void;
  settings: ComposerSettings;
  onSettingsChange: (patch: Partial<ComposerSettings>) => void;
  models: readonly ChatModel[];
  placeholder?: string;
}

const MODES: readonly { mode: RunMode; label: string; icon: typeof MessageSquareIcon }[] = [
  { mode: "chat", label: "Chat", icon: MessageSquareIcon },
  { mode: "deep_research", label: "Deep research", icon: TelescopeIcon },
];

/**
 * The prompt box: textarea + model select, Chat / Deep research mode, the Search and Code
 * toggles (Chat mode only) and a submit button that turns into Stop while a response runs.
 * Submitting is possible only when the thread is `ready` and there is text.
 */
export function ChatComposer({
  status,
  onSubmit,
  onStop,
  settings,
  onSettingsChange,
  models,
  placeholder = "Message the assistant…",
}: ChatComposerProps) {
  const [text, setText] = useState("");
  const isGenerating = status === "submitted" || status === "streaming";
  const canSubmit = status === "ready" && text.trim().length > 0;

  return (
    <PromptInput
      onSubmit={async ({ text: submitted }) => {
        const message = submitted.trim();
        if (!message || status !== "ready") {
          return;
        }
        setText("");
        await onSubmit(message);
      }}
    >
      <PromptInputBody>
        <PromptInputTextarea
          aria-label="Message"
          placeholder={placeholder}
          value={text}
          onChange={(event) => setText(event.currentTarget.value)}
        />
      </PromptInputBody>
      <PromptInputFooter>
        <PromptInputTools>
          <ModelSelect
            models={models}
            value={resolveModelId(settings, models)}
            onChange={(model) => onSettingsChange({ model })}
          />
          <div role="group" aria-label="Mode" className="flex items-center">
            {MODES.map(({ mode, label, icon: Icon }) => (
              <PromptInputButton
                key={mode}
                type="button"
                aria-pressed={settings.mode === mode}
                variant={settings.mode === mode ? "secondary" : "ghost"}
                onClick={() => onSettingsChange({ mode })}
              >
                <Icon />
                {label}
              </PromptInputButton>
            ))}
          </div>
          {settings.mode === "chat" && (
            <>
              <PromptInputButton
                type="button"
                aria-pressed={settings.webSearch}
                variant={settings.webSearch ? "secondary" : "ghost"}
                onClick={() => onSettingsChange({ webSearch: !settings.webSearch })}
              >
                <GlobeIcon />
                Search
              </PromptInputButton>
              <PromptInputButton
                type="button"
                aria-pressed={settings.code}
                variant={settings.code ? "secondary" : "ghost"}
                onClick={() => onSettingsChange({ code: !settings.code })}
              >
                <CodeIcon />
                Code
              </PromptInputButton>
            </>
          )}
        </PromptInputTools>
        <PromptInputSubmit
          status={status}
          onStop={onStop}
          disabled={isGenerating ? false : !canSubmit}
        />
      </PromptInputFooter>
    </PromptInput>
  );
}
