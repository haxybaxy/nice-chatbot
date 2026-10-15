import {
  PromptInputSelect,
  PromptInputSelectContent,
  PromptInputSelectItem,
  PromptInputSelectTrigger,
  PromptInputSelectValue,
} from "@/shared/components/ai-elements/prompt-input";

import type { ChatModel } from "../types";

interface ModelSelectProps {
  models: readonly ChatModel[];
  /** The resolved model id (see `resolveModel`), or `null` while the catalog is loading. */
  value: string | null;
  onChange: (modelId: string) => void;
}

/** The composer's model picker over `GET /api/chat/models`. */
export function ModelSelect({ models, value, onChange }: ModelSelectProps) {
  return (
    <PromptInputSelect value={value ?? undefined} onValueChange={onChange} disabled={!value}>
      <PromptInputSelectTrigger aria-label="Model" className="min-w-40">
        <PromptInputSelectValue placeholder="Loading models…" />
      </PromptInputSelectTrigger>
      <PromptInputSelectContent>
        {models.map((model) => (
          <PromptInputSelectItem key={model.id} value={model.id}>
            {model.displayName}
          </PromptInputSelectItem>
        ))}
      </PromptInputSelectContent>
    </PromptInputSelect>
  );
}
