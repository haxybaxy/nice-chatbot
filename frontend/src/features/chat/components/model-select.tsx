import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/shared/components/ui/select";

import { type ComposerSettings, resolveModel } from "../hooks/use-composer-settings";
import type { ChatModel } from "../types";

interface ModelSelectProps {
  settings: Pick<ComposerSettings, "model">;
  onSettingsChange: (patch: Partial<ComposerSettings>) => void;
  models: readonly ChatModel[];
}

/**
 * The header's model picker over `GET /api/chat/models`, as ChatGPT's: a quiet button carrying
 * the model's name. Shows the resolved model (`resolveModel`: the remembered one while the
 * catalog lists it, else the default) and is disabled while the catalog loads.
 */
export function ModelSelect({ settings, onSettingsChange, models }: ModelSelectProps) {
  // `""` rather than `undefined` while loading: a Select that is controlled from the start
  // (Radix shows the placeholder for an empty value).
  const value = resolveModel(settings, models)?.id ?? "";
  return (
    <Select value={value} onValueChange={(id) => onSettingsChange({ model: id })} disabled={!value}>
      <SelectTrigger
        aria-label="Model"
        className="gap-1 border-none bg-transparent px-2.5 text-base font-medium text-muted-foreground shadow-none transition-colors hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground data-[size=default]:h-9 dark:bg-transparent dark:hover:bg-muted"
      >
        <SelectValue placeholder="Loading models…" />
      </SelectTrigger>
      <SelectContent position="popper" align="start">
        {models.map((model) => (
          <SelectItem key={model.id} value={model.id}>
            {model.displayName}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
