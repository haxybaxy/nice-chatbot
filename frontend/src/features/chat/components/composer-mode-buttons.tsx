import { CodeIcon, GlobeIcon, MessageSquareIcon, TelescopeIcon } from "lucide-react";

import { PromptInputButton } from "@/shared/components/ai-elements/prompt-input";

import { type ComposerSettings, effectiveTools } from "../hooks/use-composer-settings";
import type { ChatModel, RunMode } from "../types";

const MODES: readonly { mode: RunMode; label: string; icon: typeof MessageSquareIcon }[] = [
  { mode: "chat", label: "Chat", icon: MessageSquareIcon },
  { mode: "deep_research", label: "Deep research", icon: TelescopeIcon },
];

interface ComposerModeButtonsProps {
  settings: ComposerSettings;
  onSettingsChange: (patch: Partial<ComposerSettings>) => void;
  /** The resolved model: its capabilities gate the toggles. `undefined` while the catalog loads. */
  model: ChatModel | undefined;
}

/**
 * Chat / Deep research, then the Search and Code toggles (Chat mode only). A toggle whose
 * capability the model lacks is disabled and reads as off — what `effectiveTools` will send.
 */
export function ComposerModeButtons({
  settings,
  onSettingsChange,
  model,
}: ComposerModeButtonsProps) {
  const tools = effectiveTools(settings, model);
  return (
    <>
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
          <ToolToggle
            label="Search"
            icon={GlobeIcon}
            pressed={tools.webSearch}
            unavailable={model !== undefined && !model.webSearch}
            unavailableReason="Web search is not available for this model"
            onToggle={() => onSettingsChange({ webSearch: !settings.webSearch })}
          />
          <ToolToggle
            label="Code"
            icon={CodeIcon}
            pressed={tools.code}
            unavailable={model !== undefined && !model.code}
            unavailableReason="Code execution is not configured on this server"
            onToggle={() => onSettingsChange({ code: !settings.code })}
          />
        </>
      )}
    </>
  );
}

interface ToolToggleProps {
  label: string;
  icon: typeof GlobeIcon;
  /** The effective value, not the remembered one. */
  pressed: boolean;
  unavailable: boolean;
  unavailableReason: string;
  onToggle: () => void;
}

function ToolToggle({
  label,
  icon: Icon,
  pressed,
  unavailable,
  unavailableReason,
  onToggle,
}: ToolToggleProps) {
  return (
    <PromptInputButton
      type="button"
      aria-pressed={pressed}
      variant={pressed ? "secondary" : "ghost"}
      disabled={unavailable}
      title={unavailable ? unavailableReason : undefined}
      onClick={onToggle}
    >
      <Icon />
      {label}
    </PromptInputButton>
  );
}
