import { CodeIcon, GlobeIcon, type LucideIcon, TelescopeIcon } from "lucide-react";

import { PromptInputButton } from "@/shared/components/ai-elements/prompt-input";
import { cn } from "@/shared/utils";

import { type ComposerSettings, effectiveTools } from "../hooks/use-composer-settings";
import type { ChatModel } from "../types";

interface ComposerModeButtonsProps {
  settings: ComposerSettings;
  onSettingsChange: (patch: Partial<ComposerSettings>) => void;
  /** The resolved model: its capabilities gate the toggles. `undefined` while the catalog loads. */
  model: ChatModel | undefined;
}

/**
 * ChatGPT's tool pills: Search and Code (chat mode only; a toggle whose capability the model
 * lacks is disabled and reads as off — what `effectiveTools` will send) and Deep research,
 * which switches the mode and hides the other two.
 */
export function ComposerModeButtons({
  settings,
  onSettingsChange,
  model,
}: ComposerModeButtonsProps) {
  const tools = effectiveTools(settings, model);
  const researching = settings.mode === "deep_research";
  return (
    <>
      {!researching && (
        <>
          <Pill
            label="Search"
            icon={GlobeIcon}
            pressed={tools.webSearch}
            unavailable={model !== undefined && !model.webSearch}
            unavailableReason="Web search is not available for this model"
            onClick={() => onSettingsChange({ webSearch: !settings.webSearch })}
          />
          <Pill
            label="Code"
            icon={CodeIcon}
            pressed={tools.code}
            unavailable={model !== undefined && !model.code}
            unavailableReason="Code execution is not configured on this server"
            onClick={() => onSettingsChange({ code: !settings.code })}
          />
        </>
      )}
      <Pill
        label="Deep research"
        icon={TelescopeIcon}
        pressed={researching}
        onClick={() => onSettingsChange({ mode: researching ? "chat" : "deep_research" })}
      />
    </>
  );
}

interface PillProps {
  label: string;
  icon: LucideIcon;
  /** The effective value, not the remembered one. */
  pressed: boolean;
  unavailable?: boolean;
  unavailableReason?: string;
  onClick: () => void;
}

/** One pill: outlined when off, blue-tinted when on; the label is read, not shown, on a phone. */
function Pill({
  label,
  icon: Icon,
  pressed,
  unavailable = false,
  unavailableReason,
  onClick,
}: PillProps) {
  return (
    <PromptInputButton
      type="button"
      variant="outline"
      size="sm"
      aria-pressed={pressed}
      disabled={unavailable}
      title={unavailable ? unavailableReason : undefined}
      className={cn(
        "h-9 rounded-full px-3 text-sm font-normal",
        pressed
          ? "border-transparent bg-blue-500/10 text-blue-600 hover:bg-blue-500/15 hover:text-blue-600 dark:bg-blue-400/15 dark:text-blue-400 dark:hover:bg-blue-400/20 dark:hover:text-blue-400"
          : "border-border bg-transparent hover:bg-muted dark:border-input dark:bg-transparent dark:hover:bg-muted"
      )}
      onClick={onClick}
    >
      <Icon className="size-4" />
      <span className="sr-only sm:not-sr-only">{label}</span>
    </PromptInputButton>
  );
}
